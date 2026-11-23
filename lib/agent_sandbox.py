#!/usr/bin/env python3
"""
Runtime sandbox for jobsOps-mediated agent tools.

Filesystem, process, network, and tool permissions are enforced here — not in
prompts. Tool handlers must be registered through AgentSandbox; raw subprocess
spawn and unrestricted HTTP are refused.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from url_safety import safe_http_fetch  # noqa: E402

ToolHandler = Callable[..., Any]


class SandboxViolation(PermissionError):
    """Raised when an agent tool attempts a disallowed operation."""


@dataclass
class AgentSandbox:
    """
    Fail-closed permission boundary for broker-registered tools.

    - Filesystem: reads/writes limited to ``workspace_root`` (and optional extras).
    - Network: only ``safe_http_fetch`` (SSRF + connect-time IP pin).
    - Process: agent tools cannot spawn subprocesses.
    - Tools: dispatch only via sealed ToolBroker (caller responsibility).
    """

    workspace_root: Path
    allow_network: bool = True
    allow_write: bool = True
    extra_readable: tuple[Path, ...] = ()
    denials: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root).resolve()
        self.extra_readable = tuple(Path(p).resolve() for p in self.extra_readable)

    def _resolve_in_workspace(self, path: Path | str, *, write: bool = False) -> Path:
        target = Path(path).resolve()
        roots = [self.workspace_root, *self.extra_readable]
        if write:
            roots = [self.workspace_root]
        for root in roots:
            try:
                target.relative_to(root)
                if write and not self.allow_write:
                    self.denials.append(f"write_disabled:{target}")
                    raise SandboxViolation("sandbox_write_disabled")
                return target
            except ValueError:
                continue
        self.denials.append(f"path_escape:{target}")
        raise SandboxViolation(f"sandbox_path_escape:{target}")

    def read_file(self, path: Path | str) -> str:
        target = self._resolve_in_workspace(path, write=False)
        if not target.is_file():
            raise SandboxViolation(f"sandbox_file_missing:{target}")
        return target.read_text(encoding="utf-8")

    def write_file(self, path: Path | str, content: str) -> str:
        target = self._resolve_in_workspace(path, write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def http_fetch(self, url: str, *, timeout: float = 12.0) -> tuple[int, str]:
        if not self.allow_network:
            self.denials.append(f"network_disabled:{url}")
            raise SandboxViolation("sandbox_network_disabled")
        return safe_http_fetch(url, timeout=timeout)

    def spawn_process(self, *args: Any, **kwargs: Any) -> None:
        self.denials.append("process_spawn_denied")
        raise SandboxViolation("sandbox_process_spawn_denied")

    def register_default_handlers(self, broker: Any) -> None:
        """Attach sandboxed handlers for tools present on the sealed broker."""
        mapping: dict[str, ToolHandler] = {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "http_fetch": self.http_fetch,
            "read_exclusion": self.read_file,
            "write_shard": self.write_file,
            "write_report": self.write_file,
        }
        for tool in sorted(broker.allowed_tools):
            if tool in {"browser", "submit"}:
                # Privileged tools stay unregistered until a dedicated adapter
                # binds them under policy + kill switches — never as raw spawn.
                continue
            handler = mapping.get(tool)
            if handler is not None:
                broker.register(tool, handler)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": str(self.workspace_root),
            "allow_network": self.allow_network,
            "allow_write": self.allow_write,
            "enforcement": "agent_sandbox",
            "os_sandbox": False,
        }


def provider_supports_native_tool_restrictions(provider: str) -> bool:
    """
    Third-party agent CLIs do not expose verifiable OS/tool sandboxes to jobsOps.
    Only the deterministic (no-spawn) path is considered enforceable by default.
    """
    return provider == "deterministic"


def require_enforceable_restrictions(
    provider: str,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """
    Fail closed when spawning an agent whose filesystem/process/network/tool
    restrictions cannot be enforced outside prompts.

    Operators may set JOBOPS_ALLOW_UNSANDBOXED_AGENT=1 to opt into residual risk
    (minimal env + ToolBroker still apply; OS sandbox still unsupported).
    """
    env = environ if environ is not None else os.environ
    if provider_supports_native_tool_restrictions(provider):
        return "deterministic"
    if (env.get("JOBOPS_ALLOW_UNSANDBOXED_AGENT") or "0") == "1":
        return "unsandboxed_opt_in"
    if (env.get("JOBOPS_REQUIRE_OS_SANDBOX") or "0") == "1":
        raise SandboxViolation(
            f"os_sandbox_unavailable_for_provider:{provider}"
        )
    raise SandboxViolation(
        f"agent_restrictions_unenforcable:{provider}:"
        "set JOBOPS_ALLOW_UNSANDBOXED_AGENT=1 to acknowledge residual risk"
    )
