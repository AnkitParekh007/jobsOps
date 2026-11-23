"""
P0/P1 trust-boundary remediation evidence.

Proves untrusted agents cannot read secrets, approve submissions, or mint
trusted evidence; covers minimal env, sandbox fail-closed, atomic reservations,
PDF fixtures, mock ATS journey, and outbound HTTP policy.
"""
from __future__ import annotations

import concurrent.futures
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime import CursorAgentRuntime, DeterministicRuntime, InvokeRequest
from agent_sandbox import AgentSandbox, SandboxViolation, require_enforceable_restrictions
from approval_controller import ApprovalAuthError, ApprovalController, mint_user_session
from evidence_issuer import EvidenceIssuanceError, TrustedEvidenceIssuer
from ledger import Ledger
from mock_ats_portal import MockAtsError, MockAtsPortal
from pdf_fixture import extract_text_ordered, fingerprint_bytes, write_text_pdf
from submission_authorize import extract_pdf_text, reserve_daily_submission
from tool_broker import ToolBroker
from trust_boundary import (
    OrchestratorContext,
    assert_env_has_no_secrets,
    build_agent_subprocess_env,
    is_secret_env_key,
)
from url_safety import safe_http_fetch
from verify_jobs import http_fetch

SECRET = b"jobops-trust-boundary-remediation-secret"


def test_agent_subprocess_env_strips_secrets(monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_APPROVAL_TOKEN", "approval-secret-value")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/creds.json")
    monkeypatch.setenv("JOBOPS_CONNECTOR_TOKEN_SHEETS", "sheets-tok")
    env = build_agent_subprocess_env(
        role="discovery",
        allowed_tools=["http_fetch", "read_file"],
        broker_session_id="sess1",
        policy_version="test",
        parent_env=os.environ,
        extra={"JOBOPS_EVIDENCE_SECRET": "inject-me", "PATH": os.environ.get("PATH", "")},
    )
    assert_env_has_no_secrets(env)
    assert "JOBOPS_EVIDENCE_SECRET" not in env
    assert "JOBOPS_APPROVAL_TOKEN" not in env
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in env
    assert "JOBOPS_CONNECTOR_TOKEN_SHEETS" not in env
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


def test_approval_controller_pending_then_authenticated_approve(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(tmp_path / "appr.db")
    led.start_run("appr-1", floor=40)
    with OrchestratorContext(principal="pytest"):
        ctl = ApprovalController(led)
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

        session = mint_user_session("user-1")
        decided = ctl.approve(approval_id="a1", user_session=session)
        assert decided["status"] == "approved"
        assert decided["decided_by"].startswith("user:")
    led.close()


def test_agent_cannot_approve_or_create_approved_row(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "frontier_submit")
    led = Ledger(tmp_path / "agent-appr.db")
    led.start_run("agent-1", floor=40)
    with pytest.raises(PermissionError):
        with OrchestratorContext(principal="evil-agent"):
            pass
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


def test_agent_cannot_mint_evidence_even_after_clearing_role(tmp_path: Path, monkeypatch):
    """Issuance requires OrchestratorContext — unsetting JOBOPS_AGENT_ROLE is not enough."""
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "discovery")
    led = Ledger(tmp_path / "mint.db")
    led.start_run("mint-1", floor=40)

    with pytest.raises(EvidenceIssuanceError, match="forbidden_in_agent_role"):
        TrustedEvidenceIssuer(led, secret=SECRET)

    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    # No orchestrator context → still refused.
    with pytest.raises(EvidenceIssuanceError, match="orchestrator_context_required"):
        TrustedEvidenceIssuer(led, secret=SECRET)

    with OrchestratorContext(principal="pytest"):
        led.record_approval(
            approval_id="ok",
            user_id="u",
            job_key="j",
            session_id="s",
            artifact_fingerprint="a" * 64,
            status="approved",
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


def test_pending_approval_cannot_issue_evidence(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(tmp_path / "pend.db")
    led.start_run("pend-1", floor=40)
    with OrchestratorContext(principal="pytest"):
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


def test_atomic_submission_reservations_enforce_daily_cap(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    db = tmp_path / "res.db"
    today = "2099-01-15"

    def attempt(i: int) -> tuple[bool, str]:
        led = Ledger(db)
        with OrchestratorContext(principal=f"worker-{i}"):
            ok, reason, _rid = reserve_daily_submission(
                led,
                job_key=f"job:{i}",
                run_id=f"run-{i}",
                cap=1,
                submit_date=today,
                reservation_id=f"res-{i}",
            )
        led.close()
        return ok, reason

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
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


def test_approval_controller_rejects_wrong_user(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(tmp_path / "wrong.db")
    led.start_run("w1", floor=40)
    with OrchestratorContext(principal="pytest"):
        ctl = ApprovalController(led)
        ctl.request_approval(
            approval_id="w",
            user_id="owner",
            job_key="j",
            session_id="s",
            artifact_fingerprint="c" * 64,
        )
        other = mint_user_session("intruder")
        with pytest.raises(ApprovalAuthError, match="user_mismatch"):
            ctl.approve(approval_id="w", user_session=other)
    led.close()
