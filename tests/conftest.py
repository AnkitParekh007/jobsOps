from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

FIXTURES = ROOT / "evals" / "fixtures"

# Installation-specific test secret (≥16 chars). Never the publicly known fallback.
_TEST_EVIDENCE_SECRET = "jobops-pytest-evidence-secret-v1"


@pytest.fixture(autouse=True)
def _jobops_test_security_defaults(monkeypatch, tmp_path_factory):
    """
    Unit/integration tests get an installation-specific evidence secret.
    Fixture fingerprints are allowed unless a test opts into live-path checks.
    Production code still fails closed when these env vars are absent.
    """
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", _TEST_EVIDENCE_SECRET)
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "1")
    # Keep live submit/outreach off unless a test explicitly enables them.
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "0")
    monkeypatch.setenv("JOBOPS_ENABLE_LIVE_SUBMIT", "0")
    monkeypatch.setenv("JOBOPS_ENABLE_OUTREACH_SEND", "0")
    # Untrusted agent CLIs fail closed unless a test opts into residual risk.
    monkeypatch.setenv("JOBOPS_ALLOW_UNSANDBOXED_AGENT", "0")
    # Enable protected control-plane bootstrap for tests (never inherited by agents).
    monkeypatch.setenv("JOBOPS_CONTROL_PLANE", "1")
    # Fresh control-plane state per test.
    from authority import reset_control_plane_for_tests

    reset_control_plane_for_tests()
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)


@pytest.fixture
def jobops_home(tmp_path, monkeypatch) -> Path:
    """Private workspace home with authority key material for control-plane tests."""
    home = tmp_path / "jobops-home"
    home.mkdir()
    (home / "secrets").mkdir()
    (home / "state").mkdir()
    monkeypatch.setenv("JOBOPS_HOME", str(home))
    from authority import reset_control_plane_for_tests

    reset_control_plane_for_tests()
    return home


@pytest.fixture
def orchestrator_ctx(jobops_home, monkeypatch) -> Iterator[Any]:
    """Enter trusted orchestrator context for approval / evidence issuance."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    from authority import reset_control_plane_for_tests
    from trust_boundary import open_orchestrator

    reset_control_plane_for_tests()
    with open_orchestrator(jobops_home, principal="pytest") as auth:
        yield auth


def control_plane_home_for(path: Path) -> Path:
    """Derive a writable control-plane home near a test ledger/db path."""
    home = Path(path).resolve().parent / "jobops-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "secrets").mkdir(exist_ok=True)
    (home / "state").mkdir(exist_ok=True)
    return home


def open_test_orchestrator(workspace_home: Path, *, principal: str = "pytest"):
    """Issue a verified grant and return an OrchestratorContext manager."""
    from authority import reset_control_plane_for_tests
    from trust_boundary import open_orchestrator

    reset_control_plane_for_tests()
    os.environ.pop("JOBOPS_AGENT_ROLE", None)
    return open_orchestrator(workspace_home, principal=principal)


def record_approved_for_test(ledger: Any, **kwargs: Any) -> str:
    """Test helper: create an approved row under verified OrchestratorContext."""
    home = control_plane_home_for(ledger.db_path)
    kwargs.setdefault("status", "approved")
    kwargs.setdefault("decided_by", "user:test")
    kwargs.setdefault("allow_overwrite", True)
    with open_test_orchestrator(home):
        return ledger.record_approval(**kwargs)
