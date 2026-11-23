"""AgentRuntime detection, forbidden flags, tool allowlists, provider smoke."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime import (
    ADAPTERS,
    FORBIDDEN_FLAGS,
    PRIVILEGED_TOOLS,
    ROLE_TOOL_SCOPES,
    AntigravityRuntime,
    ClaudeCodeRuntime,
    CodexRuntime,
    CursorAgentRuntime,
    DeterministicRuntime,
    InvokeRequest,
    ToolPermissionError,
    assert_tool_permitted,
    detect_all,
    resolve_allowed_tools,
    select_runtime,
)


def test_forbidden_flags_include_force_trust():
    assert "--force" in FORBIDDEN_FLAGS
    assert "--trust" in FORBIDDEN_FLAGS


def test_cursor_argv_never_includes_force_trust(tmp_path: Path):
    prompt = tmp_path / "p.md"
    prompt.write_text("hello", encoding="utf-8")
    rt = CursorAgentRuntime()
    info = rt.detect()
    if not info.available:
        pytest.skip("cursor agent CLI not installed")
    argv = rt.build_argv(
        InvokeRequest(
            role="discovery",
            prompt_file=prompt,
            workspace=tmp_path,
            log_out=tmp_path / "log.txt",
        )
    )
    assert "--force" not in argv
    assert "--trust" not in argv
    joined = " ".join(argv)
    assert "--force" not in joined and "--trust" not in joined
    assert "jobops-tool-allowlist" in joined
    assert "browser" not in joined.split("tools=")[-1].split("]")[0]


def test_deterministic_invoke_skips_agent(tmp_path: Path):
    prompt = tmp_path / "p.md"
    prompt.write_text("x", encoding="utf-8")
    log = tmp_path / "out.log"
    result = DeterministicRuntime().invoke(
        InvokeRequest(
            role="discovery",
            prompt_file=prompt,
            workspace=tmp_path,
            log_out=log,
        )
    )
    assert result.provider == "deterministic"
    assert result.returncode == 0
    assert "skipped" in result.message
    assert log.is_file()


def test_detect_all_and_select_deterministic(monkeypatch):
    monkeypatch.setenv("JOBOPS_RUNTIME", "deterministic")
    infos = detect_all()
    assert any(i.provider == "deterministic" and i.available for i in infos)
    assert select_runtime().provider == "deterministic"


def test_discovery_cannot_resolve_browser_or_submit():
    with pytest.raises(ToolPermissionError):
        resolve_allowed_tools("discovery", ["browser"])
    with pytest.raises(ToolPermissionError):
        resolve_allowed_tools("discovery", ["submit"])
    with pytest.raises(ToolPermissionError):
        assert_tool_permitted("discovery", "browser")
    allowed = resolve_allowed_tools("discovery")
    assert allowed.isdisjoint(PRIVILEGED_TOOLS)
    assert "http_fetch" in allowed


def test_invoke_denies_discovery_with_submit_tools(tmp_path: Path):
    prompt = tmp_path / "p.md"
    prompt.write_text("x", encoding="utf-8")
    result = DeterministicRuntime().invoke(
        InvokeRequest(
            role="discovery",
            prompt_file=prompt,
            workspace=tmp_path,
            log_out=tmp_path / "log.txt",
            allowed_tools=["http_fetch", "submit"],
        )
    )
    assert result.ok is False
    assert result.returncode == 2
    assert "tool_permission_denied" in result.message


def test_frontier_submit_may_include_browser():
    allowed = resolve_allowed_tools("frontier_submit")
    assert "browser" in allowed and "submit" in allowed


@pytest.mark.parametrize(
    "provider,cls",
    [
        ("deterministic", DeterministicRuntime),
        ("cursor", CursorAgentRuntime),
        ("claude_code", ClaudeCodeRuntime),
        ("codex", CodexRuntime),
        ("antigravity", AntigravityRuntime),
    ],
)
def test_provider_adapter_smoke(provider, cls, tmp_path: Path):
    """
    Smoke-test each adapter when its CLI is on PATH.
    Unavailable platforms are labeled unsupported (not silently claimed).
    """
    rt = cls()
    info = rt.detect()
    assert info.provider in {provider, provider.replace("_", "")} or info.provider == provider
    if not info.available:
        assert info.notes, f"{provider} must explain why unsupported"
        assert any(
            "not" in n.lower() or "detect" in n.lower() or "verify" in n.lower()
            for n in info.notes
        )
        pytest.skip(f"{provider} unsupported on this host: {info.notes}")
    prompt = tmp_path / "smoke.md"
    prompt.write_text("jobops provider smoke", encoding="utf-8")
    if provider == "deterministic":
        result = rt.invoke(
            InvokeRequest(
                role="discovery",
                prompt_file=prompt,
                workspace=tmp_path,
                log_out=tmp_path / "smoke.log",
            )
        )
        assert "skipped" in result.message
        return
    argv = rt.build_argv(
        InvokeRequest(
            role="discovery",
            prompt_file=prompt,
            workspace=tmp_path,
            log_out=tmp_path / "smoke.log",
            allowed_tools=sorted(ROLE_TOOL_SCOPES["discovery"]),
        )
    )
    assert argv
    assert "--force" not in argv and "--trust" not in argv
    assert any("jobops-tool-allowlist" in a for a in argv)


def test_adapters_registry_complete():
    assert set(ADAPTERS) >= {"deterministic", "cursor", "claude_code", "codex", "antigravity"}
