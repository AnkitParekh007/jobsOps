"""Adversarial tests: tool-scope bypass, signing-key fallback, evidence abuse, PDF mismatch."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime import ToolPermissionError
from evidence_issuer import EvidenceIssuanceError, TrustedEvidenceIssuer
from ledger import Ledger
from submission_authorize import (
    EvidenceSecretError,
    authorize_submission,
    evidence_secret,
    issue_trusted_evidence,
    recompute_pdf_fingerprint,
    validate_pdf_file,
)
from tool_broker import ToolBroker
from url_safety import validate_ip_literal


SECRET = b"jobops-adversarial-test-secret"


def test_tool_broker_blocks_scope_bypass_and_env_widen():
    broker = ToolBroker.create("discovery")
    assert not broker.permits("submit")
    assert not broker.permits("browser")

    calls: list[str] = []
    broker.register("http_fetch", lambda url: calls.append(url) or "ok")

    with pytest.raises(ToolPermissionError):
        broker.invoke("submit", token_id=broker.token.token_id)
    with pytest.raises(ToolPermissionError):
        broker.attempt_widen(["submit", "browser"])
    with pytest.raises(ToolPermissionError):
        broker.register("submit", lambda: None)
    # Forged capability token refused.
    with pytest.raises(ToolPermissionError, match="invalid_capability_token"):
        broker.invoke("http_fetch", "https://example.com", token_id="forged")
    # Valid invoke works.
    assert broker.invoke("http_fetch", "https://example.com", token_id=broker.token.token_id) == "ok"
    broker.close()
    with pytest.raises(ToolPermissionError, match="broker_closed"):
        broker.invoke("http_fetch", "https://example.com", token_id=broker.token.token_id)


def test_evidence_secret_fail_closed_no_fallback(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("JOBOPS_EVIDENCE_SECRET", raising=False)
    with pytest.raises(EvidenceSecretError, match="unavailable"):
        evidence_secret(workspace_home=tmp_path)

    # Publicly known insecure value rejected even if set in env.
    monkeypatch.setenv(
        "JOBOPS_EVIDENCE_SECRET", "jobops-dev-evidence-secret-not-for-production"
    )
    with pytest.raises(EvidenceSecretError, match="insecure"):
        evidence_secret()

    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", "short")
    with pytest.raises(EvidenceSecretError, match="insecure|too_short"):
        evidence_secret()


def test_authorize_fail_closed_without_secret(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("JOBOPS_EVIDENCE_SECRET", raising=False)
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "1")
    result = authorize_submission(
        {
            "canonical_url": "https://jobs.ashbyhq.com/acme/no-secret",
            "ats_score": 90,
            "quality_score": 85,
            "pdf_fingerprint": "a" * 64,
            "ats_score_fingerprint": "a" * 64,
            "quality_score_fingerprint": "a" * 64,
            "fingerprint_method": "fixture",
            "extracted_text": "Alex Candidate React",
        },
        run_id="no-secret",
        dry_run=True,
        require_form_lock=False,
        identity_markers=["alex", "candidate"],
        workspace_home=tmp_path,
    )
    assert result.authorized is False
    assert result.code == "evidence_secret_unavailable"
    assert any("evidence_secret" in b for b in result.blocking_reasons)


def test_evidence_issuer_requires_durable_approval(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(tmp_path / "iss.db")
    led.start_run("iss-1", floor=40)
    issuer = TrustedEvidenceIssuer(led, secret=SECRET)

    with pytest.raises(EvidenceIssuanceError, match="approval_not_found"):
        issuer.issue_claim(
            claim="user_consent",
            approval_id="missing",
            user_id="u1",
            job_key="job:1",
            session_id="s1",
            artifact_fingerprint="f" * 64,
        )

    led.record_approval(
        approval_id="appr-1",
        user_id="u1",
        job_key="job:1",
        session_id="s1",
        artifact_fingerprint="f" * 64,
        document_path="/tmp/resume.pdf",
        status="approved",
        run_id="iss-1",
    )
    rec = issuer.issue_claim(
        claim="posting_open",
        approval_id="appr-1",
        user_id="u1",
        job_key="job:1",
        session_id="s1",
        artifact_fingerprint="f" * 64,
    )
    assert rec["kind"] == "trusted_evidence_v1"
    assert rec["claim"] == "posting_open"

    # Agent role cannot mint.
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "discovery")
    with pytest.raises(EvidenceIssuanceError, match="forbidden_in_agent_role"):
        TrustedEvidenceIssuer(led, secret=SECRET)
    led.close()


def test_fixture_and_missing_pdf_rejected_on_live_path(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "0")
    monkeypatch.setenv("JOBOPS_ENABLE_LIVE_SUBMIT", "1")
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "1")

    result = authorize_submission(
        {
            "canonical_url": "https://jobs.ashbyhq.com/acme/live-fixture",
            "ats_score": 90,
            "quality_score": 85,
            "pdf_fingerprint": "a" * 64,
            "ats_score_fingerprint": "a" * 64,
            "quality_score_fingerprint": "a" * 64,
            "fingerprint_method": "fixture",
            "extracted_text": "Alex Candidate React",
        },
        run_id="live-fix",
        dry_run=False,
        require_form_lock=False,
        identity_markers=["alex", "candidate"],
        consent_auto_submit=True,
    )
    assert result.authorized is False
    assert any(
        "fixture_evidence_rejected" in b or "pdf_path_required" in b
        for b in result.blocking_reasons
    )

    # Nonexistent PDF path.
    missing = tmp_path / "nope.pdf"
    result2 = authorize_submission(
        {
            "canonical_url": "https://jobs.ashbyhq.com/acme/missing-pdf",
            "ats_score": 90,
            "quality_score": 85,
            "pdf_path": str(missing),
            "pdf_fingerprint": "a" * 64,
            "ats_score_fingerprint": "a" * 64,
            "quality_score_fingerprint": "a" * 64,
            "fingerprint_method": "sha256_bytes",
            "extracted_text": "Alex Candidate React",
        },
        run_id="missing-pdf",
        dry_run=False,
        require_form_lock=False,
        identity_markers=["alex", "candidate"],
    )
    assert result2.authorized is False
    assert any("pdf_missing" in b for b in result2.blocking_reasons)


def test_pdf_recompute_rejects_mismatch_and_non_pdf(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "0")
    monkeypatch.setenv("JOBOPS_ENABLE_LIVE_SUBMIT", "1")

    bogus = tmp_path / "not.pdf"
    bogus.write_bytes(b"not a pdf at all")
    ok, reason, _ = validate_pdf_file(bogus)
    assert ok is False
    assert reason == "pdf_invalid_magic"

    real = tmp_path / "real.pdf"
    # Minimal PDF header + padding.
    body = b"%PDF-1.4\n" + b"1" * 128 + b"\n%%EOF\n"
    real.write_bytes(body)
    ok2, reason2, fp, method = recompute_pdf_fingerprint(real)
    assert ok2 and method == "sha256_bytes" and len(fp) == 64

    result = authorize_submission(
        {
            "canonical_url": "https://jobs.ashbyhq.com/acme/fp-mismatch",
            "ats_score": 90,
            "quality_score": 85,
            "pdf_path": str(real),
            "pdf_fingerprint": "0" * 64,  # wrong claimed digest
            "ats_score_fingerprint": "0" * 64,
            "quality_score_fingerprint": "0" * 64,
            "fingerprint_method": "sha256_bytes",
            "extracted_text": "Alex Candidate React TypeScript",
        },
        run_id="fp-mismatch",
        dry_run=False,
        require_form_lock=False,
        identity_markers=["alex", "candidate"],
    )
    assert result.authorized is False
    assert any("pdf_fingerprint_mismatch_recomputed" in b for b in result.blocking_reasons)


def test_dns_rebinding_connect_ip_blocked():
    assert validate_ip_literal("127.0.0.1").ok is False
    assert validate_ip_literal("169.254.169.254").ok is False
    assert validate_ip_literal("10.0.0.5").ok is False
    # Documentation / TEST-NET also blocked.
    assert validate_ip_literal("192.0.2.1").ok is False


def test_agent_cannot_forge_without_secret(monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    good = issue_trusted_evidence(
        claim="posting_open",
        user_id="u",
        job_key="j",
        session_id="s",
        artifact_fingerprint="a" * 64,
        secret=SECRET,
    )
    forged = dict(good)
    forged["sig"] = "0" * 64
    from submission_authorize import verify_trusted_evidence

    ok, reason = verify_trusted_evidence(
        forged,
        expected_claim="posting_open",
        user_id="u",
        job_key="j",
        session_id="s",
        artifact_fingerprint="a" * 64,
        secret=SECRET,
    )
    assert ok is False
    assert reason == "evidence_sig_invalid"
