from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

FIXTURES = ROOT / "evals" / "fixtures"

# Installation-specific test secret (≥16 chars). Never the publicly known fallback.
_TEST_EVIDENCE_SECRET = "jobops-pytest-evidence-secret-v1"


@pytest.fixture(autouse=True)
def _jobops_test_security_defaults(monkeypatch):
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
