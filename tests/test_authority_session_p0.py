"""
P0-01 / P0-02 acceptance: interactive confirmation + privileged control plane.
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
    ConfirmationReceipt,
    InteractiveApprovalGate,
    issue_confirmed_session,
    mint_user_session,
)
from confirmation_test_channels import (
    EchoChallengeChannel,
    FabricatedConfirmationChannel,
)
from authority import (
    AuthorityError,
    AuthorityGrant,
    ControlPlaneController,
    bootstrap_control_plane,
    install_control_plane_privilege,
    issue_test_grant,
    privilege_path,
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
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="exp",
            user_id="owner",
            job_key="j",
            session_id="s",
            artifact_fingerprint="a" * 64,
        )
        session = issue_confirmed_session(
            ledger=led,
            workspace_home=jobops_home,
            user_id="owner",
            approval_id="exp",
            channel=EchoChallengeChannel(),
            ttl_sec=30,
        )
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
        ctl = ApprovalController(led, workspace_home=jobops_home)
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


def test_env_alone_cannot_bootstrap_without_privilege(tmp_path, monkeypatch):
    """P0-02: JOBOPS_CONTROL_PLANE=1 without OS privilege credential fails closed."""
    home = tmp_path / "no-priv"
    home.mkdir()
    (home / "secrets").mkdir()
    (home / "state").mkdir()
    monkeypatch.setenv("JOBOPS_CONTROL_PLANE", "1")
    monkeypatch.setenv("JOBOPS_HOME", str(home))
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    reset_control_plane_for_tests()
    with pytest.raises(AuthorityError, match="privilege"):
        bootstrap_control_plane(home)
    with pytest.raises(AuthorityError, match="privilege"):
        # Controller must refuse before seal checks when privilege is absent.
        ControlPlaneController(home)


def test_process_without_privileged_access_cannot_bootstrap(jobops_home: Path, monkeypatch):
    """
    P0-02 negative: child that sets control-plane env but cannot open the
    privilege credential must not bootstrap the controller.
    """
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    reset_control_plane_for_tests()
    # Ensure privilege exists for the parent, then lock it for the child.
    install_control_plane_privilege(jobops_home)
    priv = privilege_path(jobops_home)
    assert priv.is_file()
    lib = str(Path(__file__).resolve().parent.parent / "lib")
    script = f"""
import os, sys
sys.path.insert(0, {lib!r})
os.environ['JOBOPS_CONTROL_PLANE'] = '1'
os.environ['JOBOPS_HOME'] = {str(jobops_home)!r}
os.environ.pop('JOBOPS_AGENT_ROLE', None)
from authority import ControlPlaneController, bootstrap_control_plane, reset_control_plane_for_tests
reset_control_plane_for_tests()
# Remove privilege so OS open fails even with env set.
priv = {str(priv)!r}
os.chmod(priv, 0o000)
try:
    bootstrap_control_plane({str(jobops_home)!r})
    raise SystemExit(31)
except Exception as exc:
    print('bootstrap', type(exc).__name__, exc)
try:
    ControlPlaneController({str(jobops_home)!r})
    raise SystemExit(32)
except Exception as exc:
    print('controller', type(exc).__name__, exc)
# Restore for cleanup by parent.
os.chmod(priv, 0o600)
raise SystemExit(0)
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "JOBOPS_CONTROL_PLANE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    # Always restore parent-side mode.
    try:
        priv.chmod(0o600)
    except OSError:
        pass
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "privilege" in proc.stdout.lower() or "AuthorityError" in proc.stdout


def test_session_bound_to_specific_approval(jobops_home: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "bind.db")
    led.start_run("bind-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
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
        session_a = issue_confirmed_session(
            ledger=led,
            workspace_home=jobops_home,
            user_id="owner",
            approval_id="a",
            channel=EchoChallengeChannel(),
        )
        with pytest.raises(ApprovalAuthError, match="approval_mismatch|not_pending|mismatch"):
            ctl.approve(
                approval_id="b",
                user_session=session_a,
                expected_job_key="j2",
                expected_session_id="s2",
                expected_fingerprint="d" * 64,
            )
    led.close()


def test_fabricated_confirmation_rejected(jobops_home: Path, monkeypatch):
    """P0-01: fabricated challenge echo cannot mint a session."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "fab.db")
    led.start_run("fab-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="fab",
            user_id="owner",
            job_key="job:fab",
            session_id="sess-fab",
            artifact_fingerprint="e" * 64,
        )
        gate = InteractiveApprovalGate(
            led,
            jobops_home,
            channel=FabricatedConfirmationChannel("i-am-fabricated"),
        )
        with pytest.raises(ApprovalAuthError, match="confirmation_challenge_mismatch"):
            gate.confirm_and_issue_session(approval_id="fab", principal="owner")
        # Invented ConfirmationReceipt MAC must fail.
        forged = ConfirmationReceipt(
            receipt_id="crec_forged",
            approval_id="fab",
            user_id="owner",
            job_key="job:fab",
            artifact_fingerprint="e" * 64,
            action="approve",
            challenge="0" * 32,
            confirmed_at="2099-01-01T00:00:00Z",
            mac="0" * 64,
        )
        with pytest.raises(ApprovalAuthError, match="mac_invalid|not_found|confirmation"):
            mint_user_session(
                "owner",
                approval_id="fab",
                ledger=led,
                workspace_home=jobops_home,
                confirmation=forged,
            )
        # Legacy boolean is rejected.
        with pytest.raises(ApprovalAuthError, match="explicit_user_action_not_accepted"):
            mint_user_session(
                "owner",
                approval_id="fab",
                ledger=led,
                workspace_home=jobops_home,
                explicit_user_action=True,
            )
    led.close()


def test_principal_mismatch_rejected(jobops_home: Path, monkeypatch):
    """P0-01: interactive confirm fails when principal ≠ approval owner."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "pm.db")
    led.start_run("pm-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="pm",
            user_id="owner",
            job_key="job:pm",
            session_id="sess-pm",
            artifact_fingerprint="f" * 64,
        )
        with pytest.raises(ApprovalAuthError, match="principal_mismatch"):
            issue_confirmed_session(
                ledger=led,
                workspace_home=jobops_home,
                user_id="intruder",
                approval_id="pm",
                channel=EchoChallengeChannel(),
            )
    led.close()


def test_confirmation_and_approval_replay_rejected(jobops_home: Path, monkeypatch):
    """P0-01 / P1: replay of confirmation or approved session fails."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "replay.db")
    led.start_run("rp-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="rp",
            user_id="owner",
            job_key="job:rp",
            session_id="sess-rp",
            artifact_fingerprint="a" * 64,
        )
        decided = ctl.interactive_approve(
            approval_id="rp",
            principal="owner",
            expected_job_key="job:rp",
            expected_session_id="sess-rp",
            expected_fingerprint="a" * 64,
            channel=EchoChallengeChannel(),
            workspace_home=jobops_home,
        )
        assert decided["status"] == "approved"
        # Replay interactive approve on already-approved row.
        with pytest.raises(ApprovalAuthError, match="not_pending|consumed|mismatch"):
            ctl.interactive_approve(
                approval_id="rp",
                principal="owner",
                expected_job_key="job:rp",
                expected_session_id="sess-rp",
                expected_fingerprint="a" * 64,
                channel=EchoChallengeChannel(),
                workspace_home=jobops_home,
            )
    led.close()
