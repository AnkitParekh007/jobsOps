#!/usr/bin/env python3
"""Provider-neutral AgentRuntime — detect adapters; never use unrestricted --force --trust."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import POLICY_VERSION  # noqa: E402

# Least-privilege tool scopes by role (enforced in argv / prompt contract; adapters may map).
ROLE_TOOL_SCOPES: dict[str, frozenset[str]] = {
    "discovery": frozenset({"http_fetch", "read_exclusion", "write_shard", "read_file", "write_file"}),
    "verification": frozenset({"read_file", "write_file", "http_fetch"}),
    "frontier_rank": frozenset({"http_fetch", "read_file", "write_file", "write_report"}),
    "frontier_submit": frozenset(
        {"http_fetch", "read_file", "write_file", "write_report", "browser", "submit"}
    ),
    "outreach": frozenset({"read_file", "write_file"}),
    "deterministic": frozenset(),
}

FORBIDDEN_FLAGS = frozenset({"--force", "--trust", "--yolo", "--dangerously-skip-permissions"})


@dataclass
class RuntimeInfo:
    provider: str
    available: bool
    binary: Optional[str]
    version: Optional[str]
    supports_noninteractive: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "binary": self.binary,
            "version": self.version,
            "supports_noninteractive": self.supports_noninteractive,
            "notes": list(self.notes),
            "policy_version": POLICY_VERSION,
        }


@dataclass
class InvokeRequest:
    role: str
    prompt_file: Path
    workspace: Path
    log_out: Path
    timeout_sec: int = 0
    allowed_tools: Optional[Sequence[str]] = None
    extra_env: Optional[Mapping[str, str]] = None


@dataclass
class InvokeResult:
    ok: bool
    provider: str
    returncode: int
    timed_out: bool
    log_path: str
    argv: list[str]
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "provider": self.provider,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "log_path": self.log_path,
            "argv": list(self.argv),
            "message": self.message,
            "policy_version": POLICY_VERSION,
        }


class AgentRuntime:
    """Abstract adapter contract for Claude Code, Codex, Cursor, Antigravity, deterministic."""

    provider: str = "base"

    def detect(self) -> RuntimeInfo:
        raise NotImplementedError

    def build_argv(self, req: InvokeRequest) -> list[str]:
        raise NotImplementedError

    def invoke(self, req: InvokeRequest) -> InvokeResult:
        info = self.detect()
        if not info.available:
            return InvokeResult(
                False,
                self.provider,
                127,
                False,
                str(req.log_out),
                [],
                message=f"runtime unavailable: {self.provider}",
            )
        argv = self.build_argv(req)
        _assert_no_forbidden_flags(argv)
        req.log_out.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        if req.extra_env:
            env.update({k: str(v) for k, v in req.extra_env.items()})
        # Explicit authorization boundary for submit role.
        if req.role == "frontier_submit":
            if os.environ.get("JOBOPS_ALLOW_SUBMIT", "0") != "1":
                return InvokeResult(
                    False,
                    self.provider,
                    2,
                    False,
                    str(req.log_out),
                    argv,
                    message="submit blocked: JOBOPS_ALLOW_SUBMIT!=1",
                )
        try:
            with req.log_out.open("w", encoding="utf-8") as logf:
                proc = subprocess.Popen(
                    argv,
                    cwd=str(req.workspace),
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    env=env,
                )
                try:
                    timeout = req.timeout_sec if req.timeout_sec and req.timeout_sec > 0 else None
                    rc = proc.wait(timeout=timeout)
                    timed_out = False
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    rc = 124
                    timed_out = True
                    logf.write(f"\n[agent_runtime] TIMEOUT {req.timeout_sec}s killing {self.provider}\n")
        except OSError as exc:
            return InvokeResult(
                False, self.provider, 127, False, str(req.log_out), argv, message=str(exc)
            )
        return InvokeResult(
            ok=(rc == 0 and not timed_out),
            provider=self.provider,
            returncode=rc,
            timed_out=timed_out,
            log_path=str(req.log_out),
            argv=argv,
            message="ok" if rc == 0 and not timed_out else f"rc={rc}",
        )


def _assert_no_forbidden_flags(argv: Sequence[str]) -> None:
    for arg in argv:
        base = arg.split("=", 1)[0]
        if base in FORBIDDEN_FLAGS:
            raise RuntimeError(f"forbidden unrestricted flag refused: {base}")


def _which(names: Sequence[str]) -> Optional[str]:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def _version_of(binary: str) -> Optional[str]:
    try:
        out = subprocess.check_output(
            [binary, "--version"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
        return (out or "").strip().splitlines()[0][:120]
    except (OSError, subprocess.SubprocessError):
        return None


class DeterministicRuntime(AgentRuntime):
    provider = "deterministic"

    def detect(self) -> RuntimeInfo:
        return RuntimeInfo(
            self.provider,
            True,
            None,
            None,
            True,
            notes=["no AI provider; deterministic stages only"],
        )

    def build_argv(self, req: InvokeRequest) -> list[str]:
        # Deterministic mode never launches an agent process.
        return [sys.executable, "-c", "raise SystemExit('deterministic_runtime_no_agent')"]

    def invoke(self, req: InvokeRequest) -> InvokeResult:
        req.log_out.parent.mkdir(parents=True, exist_ok=True)
        msg = (
            "deterministic-only mode: agent invocation skipped "
            f"(role={req.role} prompt={req.prompt_file.name})"
        )
        req.log_out.write_text(msg + "\n", encoding="utf-8")
        return InvokeResult(
            False,
            self.provider,
            0,
            False,
            str(req.log_out),
            [],
            message=msg,
        )


class CursorAgentRuntime(AgentRuntime):
    """Cursor Agent CLI adapter — print mode, least privilege, no --force/--trust."""

    provider = "cursor"

    def detect(self) -> RuntimeInfo:
        binary = _which(["agent", "cursor-agent"])
        if not binary:
            return RuntimeInfo(
                self.provider, False, None, None, True, notes=["agent CLI not on PATH"]
            )
        return RuntimeInfo(
            self.provider,
            True,
            binary,
            _version_of(binary),
            True,
            notes=["uses --print; refuses --force/--trust"],
        )

    def build_argv(self, req: InvokeRequest) -> list[str]:
        info = self.detect()
        assert info.binary
        prompt = req.prompt_file.read_text(encoding="utf-8")
        # Authorization boundary: role scopes recorded in env for the child / audit.
        scopes = sorted(req.allowed_tools or ROLE_TOOL_SCOPES.get(req.role, frozenset()))
        # Least privilege: --print only. Never --force/--trust/--yolo.
        # Role scopes are exported via JOBOPS_ALLOWED_TOOLS for audit / future CLI flags.
        _ = scopes  # reserved for adapter-specific allowlists when CLI supports them
        return [
            info.binary,
            "--print",
            "--workspace",
            str(req.workspace),
            prompt,
        ]


class ClaudeCodeRuntime(AgentRuntime):
    provider = "claude_code"

    def detect(self) -> RuntimeInfo:
        binary = _which(["claude"])
        if not binary:
            return RuntimeInfo(self.provider, False, None, None, True, notes=["claude not on PATH"])
        return RuntimeInfo(
            self.provider,
            True,
            binary,
            _version_of(binary),
            True,
            notes=["Claude Code CLI; print/noninteractive when supported"],
        )

    def build_argv(self, req: InvokeRequest) -> list[str]:
        info = self.detect()
        assert info.binary
        prompt = req.prompt_file.read_text(encoding="utf-8")
        # Prefer print/noninteractive; never skip permissions.
        return [info.binary, "-p", "--output-format", "text", prompt]


class CodexRuntime(AgentRuntime):
    provider = "codex"

    def detect(self) -> RuntimeInfo:
        binary = _which(["codex"])
        if not binary:
            return RuntimeInfo(self.provider, False, None, None, True, notes=["codex not on PATH"])
        return RuntimeInfo(
            self.provider, True, binary, _version_of(binary), True, notes=["Codex CLI adapter"]
        )

    def build_argv(self, req: InvokeRequest) -> list[str]:
        info = self.detect()
        assert info.binary
        prompt = req.prompt_file.read_text(encoding="utf-8")
        return [info.binary, "exec", "--skip-git-repo-check", prompt]


class AntigravityRuntime(AgentRuntime):
    provider = "antigravity"

    def detect(self) -> RuntimeInfo:
        binary = _which(["antigravity", "agy"])
        if not binary:
            return RuntimeInfo(
                self.provider, False, None, None, False, notes=["Antigravity CLI not detected"]
            )
        return RuntimeInfo(
            self.provider,
            True,
            binary,
            _version_of(binary),
            False,
            notes=["verify installed CLI support before unattended use"],
        )

    def build_argv(self, req: InvokeRequest) -> list[str]:
        info = self.detect()
        assert info.binary
        prompt = req.prompt_file.read_text(encoding="utf-8")
        return [info.binary, "run", "--prompt", prompt]


ADAPTERS: dict[str, type[AgentRuntime]] = {
    "deterministic": DeterministicRuntime,
    "cursor": CursorAgentRuntime,
    "claude_code": ClaudeCodeRuntime,
    "claude": ClaudeCodeRuntime,
    "codex": CodexRuntime,
    "antigravity": AntigravityRuntime,
}


def detect_all() -> list[RuntimeInfo]:
    return [cls().detect() for cls in (
        DeterministicRuntime,
        CursorAgentRuntime,
        ClaudeCodeRuntime,
        CodexRuntime,
        AntigravityRuntime,
    )]


def select_runtime(preferred: Optional[str] = None) -> AgentRuntime:
    """
    Resolve runtime from JOBOPS_RUNTIME / preferred / auto-detect.
    Auto-detect prefers an available interactive CLI; falls back to deterministic.
    """
    name = (preferred or os.environ.get("JOBOPS_RUNTIME") or "auto").strip().lower()
    if name in ADAPTERS:
        return ADAPTERS[name]()
    if name == "auto":
        for key in ("cursor", "claude_code", "codex", "antigravity"):
            rt = ADAPTERS[key]()
            if rt.detect().available:
                return rt
        return DeterministicRuntime()
    raise ValueError(f"unknown runtime: {name}")


def role_scopes(role: str) -> frozenset[str]:
    return ROLE_TOOL_SCOPES.get(role, frozenset())


def invoke_role(
    role: str,
    prompt_file: Path,
    *,
    workspace: Path,
    log_out: Path,
    timeout_sec: int = 0,
    runtime: Optional[AgentRuntime] = None,
) -> InvokeResult:
    rt = runtime or select_runtime()
    scopes = role_scopes(role)
    req = InvokeRequest(
        role=role,
        prompt_file=Path(prompt_file),
        workspace=Path(workspace),
        log_out=Path(log_out),
        timeout_sec=timeout_sec,
        allowed_tools=sorted(scopes),
        extra_env={
            "JOBOPS_AGENT_ROLE": role,
            "JOBOPS_ALLOWED_TOOLS": ",".join(sorted(scopes)),
            "JOBOPS_POLICY_VERSION": POLICY_VERSION,
        },
    )
    return rt.invoke(req)


def _cli() -> int:
    ap = argparse.ArgumentParser(description="JobOps AgentRuntime detect / invoke")
    ap.add_argument("--detect", action="store_true")
    ap.add_argument("--runtime", default="")
    ap.add_argument("--invoke-role", default="")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--workspace", default=".")
    ap.add_argument("--log", default="")
    ap.add_argument("--timeout", type=int, default=0)
    args = ap.parse_args()
    if args.detect or not args.invoke_role:
        infos = detect_all()
        selected = select_runtime(args.runtime or None)
        out = {
            "ok": True,
            "selected": selected.detect().to_dict(),
            "runtimes": [i.to_dict() for i in infos],
            "forbidden_flags": sorted(FORBIDDEN_FLAGS),
        }
        print(json.dumps(out, indent=2))
        return 0
    if not args.prompt or not args.log:
        print(json.dumps({"ok": False, "error": "--prompt and --log required"}), file=sys.stderr)
        return 2
    rt = select_runtime(args.runtime or None)
    result = invoke_role(
        args.invoke_role,
        Path(args.prompt),
        workspace=Path(args.workspace),
        log_out=Path(args.log),
        timeout_sec=args.timeout,
        runtime=rt,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok or result.provider == "deterministic" else result.returncode


if __name__ == "__main__":
    raise SystemExit(_cli())
