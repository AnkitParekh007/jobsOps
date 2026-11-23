"""
P0/P1 trust-boundary remediation evidence.

Proves untrusted agents cannot read secrets, approve submissions, or mint
trusted evidence; covers minimal env, sandbox fail-closed, atomic reservations,
PDF fixtures, mock ATS journey, and outbound HTTP policy.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime import CursorAgentRuntime, DeterministicRuntime, InvokeRequest
from agent_sandbox import AgentSandbox, SandboxViolation, require_enforceable_restrictions
from approval_controller import (
    ApprovalAuthError,
    ApprovalController,
    UserSession,
    issue_confirmed_session,
    mint_user_session,
)
from confirmation_test_channels import EchoChallengeChannel
from authority import (
    AuthorityError,
    ControlPlaneController,
    bootstrap_control_plane,
    reset_control_plane_for_tests,
)
from evidence_issuer import EvidenceIssuanceError, TrustedEvidenceIssuer
from ledger import Ledger
from mock_ats_portal import MockAtsError, MockAtsPortal
from pdf_fixture import extract_text_ordered, fingerprint_bytes, write_text_pdf
from submission_authorize import extract_pdf_text, reserve_daily_submission
from tool_broker import ToolBroker
from trust_boundary import (
    OrchestratorContext,
    assert_agent_env_isolated,
    assert_env_has_no_secrets,
    build_agent_subprocess_env,
    is_secret_env_key,
    open_orchestrator,
)
from url_safety import safe_http_fetch
from verify_jobs import http_fetch

SECRET = b"jobops-trust-boundary-remediation-secret"


def test_agent_subprocess_env_strips_secrets(monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_APPROVAL_TOKEN", "approval-secret-value")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/creds.json")
    monkeypatch.setenv("JOBOPS_CONNECTOR_TOKEN_SHEETS", "sheets-tok")
    monkeypatch.setenv("JOBOPS_HOME", "/tmp/secret-home")
    monkeypatch.setenv("PYTHONPATH", "/tmp/evil-path")
    env = build_agent_subprocess_env(
        role="discovery",
        allowed_tools=["http_fetch", "read_file"],
        broker_session_id="sess1",
        policy_version="test",
        parent_env=os.environ,
        extra={"JOBOPS_EVIDENCE_SECRET": "inject-me", "PATH": os.environ.get("PATH", "")},
    )
    assert_env_has_no_secrets(env)
    assert_agent_env_isolated(env)
    assert "JOBOPS_EVIDENCE_SECRET" not in env
    assert "JOBOPS_APPROVAL_TOKEN" not in env
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in env
    assert "JOBOPS_CONNECTOR_TOKEN_SHEETS" not in env
    assert "JOBOPS_HOME" not in env
    assert "PYTHONPATH" not in env
    assert env["JOBOPS_AGENT_ROLE"] == "discovery"
    assert "http_fetch" in env["JOBOPS_ALLOWED_TOOLS"]
    assert is_secret_env_key("JOBOPS_HMAC_KEY")


def test_agent_child_process_cannot_read_evidence_secret(tmp_path: Path, monkeypatch):
    """Spawn a real child with minimal env; secret must be absent from os.environ."""
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    env = build_agent_subprocess_env(
        role="discovery",
        allowed_tools=["read_file"],
        parent_env=os.environ,
    )
    script = (
        "import os,sys;"
        "sys.exit(0 if 'JOBOPS_EVIDENCE_SECRET' not in os.environ else 11)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_cursor_invoke_fails_closed_without_unsandboxed_opt_in(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_ALLOW_UNSANDBOXED_AGENT", "0")
    prompt = tmp_path / "p.md"
    prompt.write_text("x", encoding="utf-8")
    rt = CursorAgentRuntime()
    # Force "available" path by stubbing detect if CLI missing — use build path via invoke.
    # If CLI unavailable, invoke returns unavailable; still assert sandbox gate when available.
    info = rt.detect()
    if not info.available:
        # Still verify the restriction helper itself fails closed for cursor.
        with pytest.raises(SandboxViolation, match="unenforcable|unavailable"):
            require_enforceable_restrictions("cursor", environ={"JOBOPS_ALLOW_UNSANDBOXED_AGENT": "0"})
        return
    result = rt.invoke(
        InvokeRequest(
            role="discovery",
            prompt_file=prompt,
            workspace=tmp_path,
            log_out=tmp_path / "log.txt",
        )
    )
    assert result.ok is False
    assert "sandbox_fail_closed" in result.message


def test_unsandboxed_opt_in_forbidden_for_sensitive_roles():
    with pytest.raises(SandboxViolation, match="unsandboxed_forbidden_for_sensitive_role"):
        require_enforceable_restrictions(
            "cursor",
            role="frontier_submit",
            environ={"JOBOPS_ALLOW_UNSANDBOXED_AGENT": "1"},
        )
    with pytest.raises(SandboxViolation, match="unsandboxed_forbidden_for_sensitive_role"):
        require_enforceable_restrictions(
            "claude_code",
            role="outreach",
            environ={"JOBOPS_ALLOW_UNSANDBOXED_AGENT": "1"},
        )


def test_deterministic_invoke_still_works(tmp_path: Path):
    prompt = tmp_path / "p.md"
    prompt.write_text("x", encoding="utf-8")
    result = DeterministicRuntime().invoke(
        InvokeRequest(
            role="discovery",
            prompt_file=prompt,
            workspace=tmp_path,
            log_out=tmp_path / "d.log",
        )
    )
    assert "skipped" in result.message
    assert result.broker_session_id


def test_sandbox_blocks_path_escape_network_and_spawn(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "ok.txt").write_text("hello", encoding="utf-8")
    secret = tmp_path / "secrets" / "evidence_hmac.key"
    secret.parent.mkdir()
    secret.write_text("super-secret-key-value", encoding="utf-8")

    box = AgentSandbox(workspace_root=ws, allow_network=True)
    assert box.read_file(ws / "ok.txt") == "hello"
    with pytest.raises(SandboxViolation, match="path_escape"):
        box.read_file(secret)
    with pytest.raises(SandboxViolation, match="process_spawn"):
        box.spawn_process(["echo", "nope"])

    broker = ToolBroker.create("discovery", requested=["http_fetch", "read_file", "write_file"])
    box.register_default_handlers(broker)
    status, body = broker.invoke(
        "http_fetch", "http://127.0.0.1/", token_id=broker.token.token_id
    )
    assert status == 0
    assert "ssrf_blocked" in body
    with pytest.raises(Exception):
        broker.invoke("read_file", str(secret), token_id=broker.token.token_id)
    broker.close()


def test_approval_controller_pending_then_authenticated_approve(jobops_home: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "appr.db")
    led.start_run("appr-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="a1",
            user_id="user-1",
            job_key="job:1",
            session_id="sess-1",
            artifact_fingerprint="f" * 64,
            document_path="/tmp/r.pdf",
            run_id="appr-1",
        )
        row = led.get_approval("a1")
        assert row is not None
        assert row["status"] == "pending"

        session = issue_confirmed_session(
            ledger=led,
            workspace_home=jobops_home,
            user_id="user-1",
            approval_id="a1",
            channel=EchoChallengeChannel(),
        )
        decided = ctl.approve(
            approval_id="a1",
            user_session=session,
            expected_job_key="job:1",
            expected_session_id="sess-1",
            expected_fingerprint="f" * 64,
        )
        assert decided["status"] == "approved"
        assert decided["decided_by"].startswith("user:")
    led.close()


def test_agent_cannot_approve_or_create_approved_row(jobops_home: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "frontier_submit")
    led = Ledger(jobops_home / "state" / "agent-appr.db")
    led.start_run("agent-1", floor=40)
    with pytest.raises((PermissionError, AuthorityError)):
        bootstrap_control_plane(jobops_home)
    with pytest.raises(PermissionError):
        led.record_approval(
            approval_id="evil",
            user_id="user-1",
            job_key="job:1",
            session_id="s",
            artifact_fingerprint="f" * 64,
            status="approved",
        )
    led.close()


def test_clearing_agent_role_cannot_grant_authority(jobops_home: Path, monkeypatch):
    """P0-02: clearing JOBOPS_AGENT_ROLE after contamination cannot mint authority."""
    reset_control_plane_for_tests()
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "discovery")
    with pytest.raises(AuthorityError, match="agent"):
        bootstrap_control_plane(jobops_home)
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    # Contamination persists — clearing the env var is not enough.
    with pytest.raises(AuthorityError, match="contamination"):
        bootstrap_control_plane(jobops_home)
    with pytest.raises(AuthorityError, match="contamination|agent"):
        ControlPlaneController(jobops_home)


def test_agent_subprocess_clearing_role_cannot_open_orchestrator(
    jobops_home: Path, monkeypatch
):
    """Cross-process: agent child that clears JOBOPS_AGENT_ROLE still lacks authority."""
    reset_control_plane_for_tests()
    bootstrap_control_plane(jobops_home)
    key_path = jobops_home / "secrets" / "orchestrator_authority.key"
    assert key_path.is_file()

    env = build_agent_subprocess_env(
        role="discovery",
        allowed_tools=["read_file"],
        parent_env=os.environ,
    )
    # Even if the child learns the key path, JOBOPS_HOME is stripped.
    script = f"""
import os, sys
sys.path.insert(0, {str(Path(__file__).resolve().parent.parent / 'lib')!r})
# Adversary clears the role and even tries to forge control-plane enablement.
os.environ.pop('JOBOPS_AGENT_ROLE', None)
os.environ['JOBOPS_CONTROL_PLANE'] = '1'
from authority import bootstrap_control_plane, note_agent_role
from trust_boundary import open_orchestrator
# Role was present at process start via env; mark contamination as runtime would.
note_agent_role('discovery')
home = {str(jobops_home)!r}
try:
    bootstrap_control_plane(home)
    print('BOOTSTRAP_OK')
    sys.exit(11)
except Exception as exc:
    print('bootstrap_blocked', type(exc).__name__, exc)
try:
    # Clearing role still leaves contamination.
    os.environ.pop('JOBOPS_AGENT_ROLE', None)
    with open_orchestrator(home):
        print('OPEN_OK')
        sys.exit(12)
except Exception as exc:
    print('open_blocked', type(exc).__name__, exc)
sys.exit(0)
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=str(jobops_home),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "BOOTSTRAP_OK" not in proc.stdout
    assert "OPEN_OK" not in proc.stdout


def test_agent_cannot_mint_evidence_even_after_clearing_role(jobops_home: Path, monkeypatch):
    """Issuance requires verified OrchestratorContext — unsetting JOBOPS_AGENT_ROLE is not enough."""
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "discovery")
    led = Ledger(jobops_home / "state" / "mint.db")
    led.start_run("mint-1", floor=40)

    with pytest.raises(EvidenceIssuanceError, match="forbidden_in_agent_role"):
        TrustedEvidenceIssuer(led, secret=SECRET)

    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    # Contaminated process still cannot bootstrap / issue.
    with pytest.raises(EvidenceIssuanceError, match="orchestrator_context_required"):
        TrustedEvidenceIssuer(led, secret=SECRET)

    reset_control_plane_for_tests()
    with open_orchestrator(jobops_home, principal="pytest"):
        led.record_approval(
            approval_id="ok",
            user_id="u",
            job_key="j",
            session_id="s",
            artifact_fingerprint="a" * 64,
            status="approved",
            allow_overwrite=True,
        )
        issuer = TrustedEvidenceIssuer(led, secret=SECRET)
        rec = issuer.issue_claim(
            claim="posting_open",
            approval_id="ok",
            user_id="u",
            job_key="j",
            session_id="s",
            artifact_fingerprint="a" * 64,
        )
        assert rec["sig"]
    led.close()


def test_pending_approval_cannot_issue_evidence(jobops_home: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "pend.db")
    led.start_run("pend-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led)
        ctl.request_approval(
            approval_id="pend",
            user_id="u",
            job_key="j",
            session_id="s",
            artifact_fingerprint="b" * 64,
        )
        issuer = TrustedEvidenceIssuer(led, secret=SECRET)
        with pytest.raises(EvidenceIssuanceError, match="approval_not_approved:pending"):
            issuer.issue_claim(
                claim="user_consent",
                approval_id="pend",
                user_id="u",
                job_key="j",
                session_id="s",
                artifact_fingerprint="b" * 64,
            )
    led.close()


def _reserve_cap_worker(args: tuple) -> tuple[bool, str]:
    db, home, i, today = args
    os.environ["JOBOPS_CONTROL_PLANE"] = "1"
    os.environ.setdefault("PYTEST_CURRENT_TEST", "spawn-worker-reserve-cap")
    os.environ["JOBOPS_ALLOW_TEST_CONTROL_PLANE_RESET"] = "1"
    os.environ.pop("JOBOPS_AGENT_ROLE", None)
    reset_control_plane_for_tests()
    led = Ledger(db)
    try:
        with open_orchestrator(Path(home), principal=f"worker-{i}"):
            ok, reason, _rid = reserve_daily_submission(
                led,
                job_key=f"job:{i}",
                run_id=f"run-{i}",
                cap=1,
                submit_date=today,
                reservation_id=f"res-{i}",
            )
        return ok, reason
    finally:
        led.close()


def test_atomic_submission_reservations_enforce_daily_cap(jobops_home: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    monkeypatch.setenv("JOBOPS_CONTROL_PLANE", "1")
    db = str(jobops_home / "state" / "res.db")
    home = str(jobops_home)
    today = "2099-01-15"
    reset_control_plane_for_tests()
    bootstrap_control_plane(jobops_home)
    Ledger(db).close()

    with mp.get_context("spawn").Pool(processes=4) as pool:
        results = pool.map(
            _reserve_cap_worker,
            [(db, home, i, today) for i in range(8)],
        )
    successes = [r for r in results if r[0]]
    failures = [r for r in results if not r[0]]
    assert len(successes) == 1
    assert len(failures) == 7
    assert all("cap" in r[1] or "reserved" in r[1] for r in failures)


def test_real_pdf_fixture_extraction_fingerprint_identity(tmp_path: Path):
    pdf = tmp_path / "Alex_Candidate_Acme_Engineer.pdf"
    pages = [
        "Alex Candidate — Frontend Engineer",
        "Skills: Angular React TypeScript",
        "Location: India | Sponsorship: seeking",
    ]
    fp, raw = write_text_pdf(pdf, pages)
    assert raw.startswith(b"%PDF")
    assert fp == fingerprint_bytes(raw)
    assert len(fp) == 64

    ordered, page_list = extract_text_ordered(pdf)
    assert page_list[0].startswith("Alex Candidate")
    assert "Angular React TypeScript" in page_list[1]
    assert page_list[0] != page_list[2]
    # extract_pdf_text (authorize path) must see identity markers in order.
    text = extract_pdf_text(pdf)
    assert "Alex Candidate" in text
    assert text.index("Alex Candidate") < text.index("Angular React TypeScript")
    lower = text.lower()
    assert "alex" in lower and "candidate" in lower


def test_mock_ats_full_browser_journey():
    portal = MockAtsPortal(confirm_timeout_sec=1.0)
    opened = portal.open_form()
    assert opened["ok"]
    portal.fill_field("name", "Alex Candidate")
    portal.fill_field("email", "alex@example.test")
    assert portal.state == "form_open"
    portal.fill_field("resume", "/tmp/Alex_Candidate.pdf")
    assert portal.state == "filled"

    conf = portal.submit()
    assert conf["ok"] is True
    assert conf["outcome"] == "Applied"
    assert portal.state == "confirmed"

    with pytest.raises(MockAtsError, match="duplicate_submit"):
        portal.try_submit_again()

    # Timeout path on a fresh portal.
    slow = MockAtsPortal(confirm_timeout_sec=0.0)
    slow.open_form()
    slow.fill_field("name", "Alex")
    slow.fill_field("email", "a@b.c")
    slow.fill_field("resume", "r.pdf")
    timed = slow.submit(force_timeout=True)
    assert timed.get("pending") is True
    out = slow.await_confirmation(timeout_sec=0.0)
    assert out["outcome"] == "SubmissionUncertain"
    assert out["retryable"] is False


def test_outbound_http_paths_share_url_safety_policy():
    # verify_jobs.http_fetch is an alias onto safe_http_fetch policy.
    assert http_fetch.__doc__
    s1, b1 = safe_http_fetch("http://127.0.0.1/")
    s2, b2 = http_fetch("http://127.0.0.1/")
    assert s1 == 0 and s2 == 0
    assert "ssrf_blocked" in b1 and "ssrf_blocked" in b2


def test_approval_controller_rejects_wrong_user(jobops_home: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "wrong.db")
    led.start_run("w1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="w",
            user_id="owner",
            job_key="j",
            session_id="s",
            artifact_fingerprint="c" * 64,
        )
        with pytest.raises(ApprovalAuthError, match="principal_mismatch|user_mismatch|user_id"):
            issue_confirmed_session(
                ledger=led,
                workspace_home=jobops_home,
                user_id="intruder",
                approval_id="w",
                channel=EchoChallengeChannel(),
            )
    led.close()


def test_fabricated_session_and_replay_rejected(jobops_home: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "forge.db")
    led.start_run("forge-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="f1",
            user_id="owner",
            job_key="job:f",
            session_id="sess-f",
            artifact_fingerprint="d" * 64,
        )
        forged = UserSession(
            user_id="owner",
            session_token="x" * 32,
            session_id="usess_forged",
            approval_id="f1",
        )
        with pytest.raises(ApprovalAuthError, match="not_found|mismatch|token"):
            ctl.approve(
                approval_id="f1",
                user_session=forged,
                expected_job_key="job:f",
                expected_session_id="sess-f",
                expected_fingerprint="d" * 64,
            )
        session = issue_confirmed_session(
            ledger=led,
            workspace_home=jobops_home,
            user_id="owner",
            approval_id="f1",
            channel=EchoChallengeChannel(),
        )
        decided = ctl.approve(
            approval_id="f1",
            user_session=session,
            expected_job_key="job:f",
            expected_session_id="sess-f",
            expected_fingerprint="d" * 64,
        )
        assert decided["status"] == "approved"
        # Replay with same session token must fail (consumed).
        with pytest.raises(ApprovalAuthError, match="consumed|not_pending"):
            ctl.approve(
                approval_id="f1",
                user_session=session,
                expected_job_key="job:f",
                expected_session_id="sess-f",
                expected_fingerprint="d" * 64,
            )
    led.close()


def test_explicit_user_action_boolean_rejected(jobops_home: Path, monkeypatch):
    """Caller-controlled explicit_user_action is no longer accepted as proof."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "explicit.db")
    led.start_run("ex-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="e1",
            user_id="owner",
            job_key="j",
            session_id="s",
            artifact_fingerprint="e" * 64,
        )
        with pytest.raises(ApprovalAuthError, match="explicit_user_action_not_accepted"):
            mint_user_session(
                "owner",
                approval_id="e1",
                ledger=led,
                workspace_home=jobops_home,
                explicit_user_action=True,
            )
        with pytest.raises(ApprovalAuthError, match="confirmation_receipt_required"):
            mint_user_session(
                "owner",
                approval_id="e1",
                ledger=led,
                workspace_home=jobops_home,
                explicit_user_action=False,
            )
    led.close()


def test_direct_orchestrator_context_requires_grant(jobops_home: Path, monkeypatch):
    """Negative: OrchestratorContext cannot be opened without a verified grant."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    reset_control_plane_for_tests()
    with pytest.raises(TypeError):
        # Missing required grant/workspace_home kwargs.
        with OrchestratorContext(principal="evil"):  # type: ignore[call-arg]
            pass
