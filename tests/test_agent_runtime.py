"""AgentRuntime detection, forbidden flags, deterministic adapter."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime import (
    FORBIDDEN_FLAGS,
    CursorAgentRuntime,
    DeterministicRuntime,
    InvokeRequest,
    detect_all,
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
