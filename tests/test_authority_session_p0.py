"""
P0-01 / P0-02 acceptance: trusted sessions + protected orchestrator authority.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from approval_controller import (
    ApprovalAuthError,
    ApprovalController,
    mint_user_session,
)
from authority import (
    AuthorityError,
    AuthorityGrant,
    ControlPlaneController,
    bootstrap_control_plane,
    issue_test_grant,
    reset_control_plane_for_tests,
    verify_authority_grant,
)
from ledger import Ledger
from trust_boundary import OrchestratorContext, build_agent_subprocess_env, open_orchestrator


def test_expired_session_rejected(jobops_home: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "exp.db")
    led.start_run("exp-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led)
        ctl.request_approval(
            approval_id="exp",
            user_id="owner",
            job_key="j",
            session_id="s",
            artifact_fingerprint="a" * 64,
        )
        session = mint_user_session(
            "owner",
            approval_id="exp",
            ledger=led,
            explicit_user_action=True,
            ttl_sec=30,
        )
        # Force expiry in stored row.
        led._conn.execute(  # noqa: SLF001
            "UPDATE user_sessions SET expires_at=? WHERE session_id=?",
            (
                (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                session.session_id,
            ),
        )
        led._conn.commit()  # noqa: SLF001
        with pytest.raises(ApprovalAuthError, match="expired"):
            ctl.approve(
                approval_id="exp",
                user_session=session,
                expected_job_key="j",
                expected_session_id="s",
                expected_fingerprint="a" * 64,
            )
    led.close()


def test_arbitrary_user_id_rejected(jobops_home: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "arb.db")
    led.start_run("arb-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led)
        with pytest.raises(ApprovalAuthError, match="user_id_rejected"):
            ctl.request_approval(
                approval_id="arb",
                user_id="admin",
                job_key="j",
                session_id="s",
                artifact_fingerprint="b" * 64,
            )
    led.close()


def test_fabricated_authority_grant_rejected(jobops_home: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    reset_control_plane_for_tests()
    bootstrap_control_plane(jobops_home)
    forged = AuthorityGrant(
        grant_id="grant_forged",
        principal="attacker",
        scopes=frozenset({"approve", "issue_evidence", "reserve_submit", "record_approval"}),
        issued_at="2020-01-01T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
        signature="0" * 64,
        workspace_fingerprint="0" * 32,
    )
    with pytest.raises(AuthorityError, match="signature|workspace"):
        verify_authority_grant(forged, workspace_home=jobops_home)
    with pytest.raises(AuthorityError, match="signature|workspace"):
        with OrchestratorContext(grant=forged, workspace_home=jobops_home):
            pass


def test_direct_import_privilege_escalation_blocked(jobops_home: Path, monkeypatch):
    """Negative: importing ControlPlaneController / OrchestratorContext is not enough."""
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "frontier_submit")
    reset_control_plane_for_tests()
    with pytest.raises(AuthorityError):
        ControlPlaneController(jobops_home)
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    with pytest.raises(AuthorityError, match="contamination"):
        issue_test_grant(jobops_home, principal="evil")


def test_child_process_cannot_escalate_by_clearing_role(jobops_home: Path):
    reset_control_plane_for_tests()
    bootstrap_control_plane(jobops_home)
    env = build_agent_subprocess_env(role="verification", parent_env=os.environ)
    assert "JOBOPS_CONTROL_PLANE" not in env
    lib = str(Path(__file__).resolve().parent.parent / "lib")
    script = f"""
import os, sys
sys.path.insert(0, {lib!r})
os.environ.pop('JOBOPS_AGENT_ROLE', None)
# Even forging the control-plane flag after contamination must fail.
os.environ['JOBOPS_CONTROL_PLANE'] = '1'
from authority import ControlPlaneController, bootstrap_control_plane, note_agent_role
note_agent_role('verification')
try:
    bootstrap_control_plane({str(jobops_home)!r})
    raise SystemExit(21)
except Exception as exc:
    print('bootstrap', type(exc).__name__, exc)
try:
    ControlPlaneController({str(jobops_home)!r})
    raise SystemExit(22)
except Exception as exc:
    print('controller', type(exc).__name__, exc)
raise SystemExit(0)
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_session_bound_to_specific_approval(jobops_home: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "bind.db")
    led.start_run("bind-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led)
        ctl.request_approval(
            approval_id="a",
            user_id="owner",
            job_key="j1",
            session_id="s1",
            artifact_fingerprint="c" * 64,
        )
        ctl.request_approval(
            approval_id="b",
            user_id="owner",
            job_key="j2",
            session_id="s2",
            artifact_fingerprint="d" * 64,
        )
        session_a = mint_user_session(
            "owner",
            approval_id="a",
            ledger=led,
            explicit_user_action=True,
        )
        with pytest.raises(ApprovalAuthError, match="approval_mismatch|not_pending"):
            ctl.approve(
                approval_id="b",
                user_session=session_a,
                expected_job_key="j2",
                expected_session_id="s2",
                expected_fingerprint="d" * 64,
            )
    led.close()
