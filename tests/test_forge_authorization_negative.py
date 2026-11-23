"""Negative tests: agents cannot forge consent, approval, session, or evidence."""
from __future__ import annotations

from pathlib import Path

from ledger import Ledger
from submission_authorize import (
    acquire_form_lock,
    authorize_submission,
    issue_consent_record,
    issue_trusted_evidence,
    verify_trusted_evidence,
)

SECRET = b"jobops-test-forge-secret"
USER = "user-alex"
SESSION = "sess-forge-1"
APPROVAL = "approval-forge-1"


def _base_pkg(tmp_url: str = "https://jobs.ashbyhq.com/acme/forge-1") -> dict:
    fp = "f" * 64
    return {
        "canonical_url": tmp_url,
        "job_key": f"url:{tmp_url}",
        "organization": "Acme",
        "role": "Engineer",
        "ats_score": 90,
        "quality_score": 85,
        "pdf_fingerprint": fp,
        "ats_score_fingerprint": fp,
        "quality_score_fingerprint": fp,
        "fingerprint_method": "fixture",
        "extracted_text": "Alex Candidate\nAngular React TypeScript",
    }


def _mint_all(*, job_key: str, fingerprint: str) -> dict:
    out: dict = {"user_id": USER, "session_id": SESSION, "approval_id": APPROVAL}
    for claim in (
        "posting_open",
        "not_duplicate",
        "hard_eligibility_met",
        "filenames_correct",
        "required_fields_complete",
        "screening_answers_verified",
        "no_auth_wall",
        "portal_session",
    ):
        out[claim] = issue_trusted_evidence(
            claim=claim,
            user_id=USER,
            job_key=job_key,
            session_id=SESSION,
            artifact_fingerprint=fingerprint,
            secret=SECRET,
        )
    out["user_consent"] = issue_consent_record(
        user_id=USER,
        job_key=job_key,
        session_id=SESSION,
        artifact_fingerprint=fingerprint,
        approval_id=APPROVAL,
        secret=SECRET,
    )
    return out


def _authorize(pkg: dict, tmp_path: Path, monkeypatch) -> object:
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "1")
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "1")
    db = tmp_path / "forge.db"
    led = Ledger(db)
    led.start_run("forge-1", floor=40, phase="authorize")
    acquire_form_lock(led, canonical_url=pkg["canonical_url"], run_id="forge-1")
    # Durable approval bound to user/job/session/document — required for consent.
    evidence = pkg.get("evidence_package") or {}
    from trust_boundary import open_orchestrator

    home = tmp_path / "jobops-home"
    home.mkdir(exist_ok=True)
    with open_orchestrator(home, principal="pytest"):
        led.record_approval(
            approval_id=str(evidence.get("approval_id") or APPROVAL),
            user_id=str(evidence.get("user_id") or USER),
            job_key=str(pkg.get("job_key") or ""),
            session_id=str(evidence.get("session_id") or SESSION),
            artifact_fingerprint=str(pkg.get("pdf_fingerprint") or ""),
            status="approved",
            run_id="forge-1",
        )
        result = authorize_submission(
            pkg,
            run_id="forge-1",
            ledger=led,
            dry_run=False,
            require_form_lock=True,
            submits_today=0,
            identity_markers=["alex", "candidate"],
            consent_auto_submit=True,
        )
    led.close()
    return result


def test_self_asserted_verified_true_is_rejected(tmp_path: Path, monkeypatch):
    pkg = _base_pkg()
    pkg["evidence_package"] = {
        "user_id": USER,
        "session_id": SESSION,
        "approval_id": APPROVAL,
        "posting_open": {"verified": True, "method": "http_head"},
        "not_duplicate": {"verified": True, "method": "ledger"},
        "hard_eligibility_met": {"verified": True, "method": "policy"},
        "filenames_correct": {"verified": True, "method": "fn"},
        "required_fields_complete": {"verified": True, "method": "scan"},
        "screening_answers_verified": {"verified": True, "method": "facts"},
        "no_auth_wall": {"verified": True, "method": "probe"},
        "portal_session": {"status": "authorized", "session_id": SESSION, "account_id": "a1"},
        "user_consent": {"verified": True, "consent_id": "c1", "method": "workspace"},
    }
    result = _authorize(pkg, tmp_path, monkeypatch)
    assert result.authorized is False
    assert any("self_asserted" in b or "untrusted" in b for b in result.blocking_reasons)


def test_forged_hmac_signature_rejected(tmp_path: Path, monkeypatch):
    pkg = _base_pkg()
    evidence = _mint_all(job_key=pkg["job_key"], fingerprint=pkg["pdf_fingerprint"])
    evidence["user_consent"]["sig"] = "0" * 64  # forged
    pkg["evidence_package"] = evidence
    result = _authorize(pkg, tmp_path, monkeypatch)
    assert result.authorized is False
    assert any("sig_invalid" in b for b in result.blocking_reasons)


def test_consent_bound_to_wrong_job_rejected(tmp_path: Path, monkeypatch):
    pkg = _base_pkg()
    evidence = _mint_all(job_key=pkg["job_key"], fingerprint=pkg["pdf_fingerprint"])
    # Re-mint consent for a different requisition (cross-job forge).
    evidence["user_consent"] = issue_consent_record(
        user_id=USER,
        job_key="url:https://jobs.ashbyhq.com/acme/OTHER",
        session_id=SESSION,
        artifact_fingerprint=pkg["pdf_fingerprint"],
        approval_id=APPROVAL,
        secret=SECRET,
    )
    pkg["evidence_package"] = evidence
    result = _authorize(pkg, tmp_path, monkeypatch)
    assert result.authorized is False
    assert any("job_mismatch" in b for b in result.blocking_reasons)


def test_consent_bound_to_wrong_fingerprint_rejected(tmp_path: Path, monkeypatch):
    pkg = _base_pkg()
    evidence = _mint_all(job_key=pkg["job_key"], fingerprint=pkg["pdf_fingerprint"])
    evidence["user_consent"] = issue_consent_record(
        user_id=USER,
        job_key=pkg["job_key"],
        session_id=SESSION,
        artifact_fingerprint="e" * 64,
        approval_id=APPROVAL,
        secret=SECRET,
    )
    pkg["evidence_package"] = evidence
    result = _authorize(pkg, tmp_path, monkeypatch)
    assert result.authorized is False
    assert any("fingerprint_mismatch" in b for b in result.blocking_reasons)


def test_session_bound_to_wrong_user_rejected(tmp_path: Path, monkeypatch):
    pkg = _base_pkg()
    evidence = _mint_all(job_key=pkg["job_key"], fingerprint=pkg["pdf_fingerprint"])
    evidence["portal_session"] = issue_trusted_evidence(
        claim="portal_session",
        user_id="attacker",
        job_key=pkg["job_key"],
        session_id=SESSION,
        artifact_fingerprint=pkg["pdf_fingerprint"],
        secret=SECRET,
    )
    evidence["user_id"] = "attacker"  # try to align package user to attacker
    pkg["evidence_package"] = evidence
    result = _authorize(pkg, tmp_path, monkeypatch)
    assert result.authorized is False
    # Consent still bound to user-alex → mismatch vs attacker session package.
    assert any("mismatch" in b or "sig_invalid" in b for b in result.blocking_reasons)


def test_bare_approval_id_without_trusted_consent_rejected(tmp_path: Path, monkeypatch):
    pkg = _base_pkg()
    evidence = _mint_all(job_key=pkg["job_key"], fingerprint=pkg["pdf_fingerprint"])
    evidence["user_consent"] = True  # forge
    evidence["approval_id"] = "spoofed-approval"
    pkg["evidence_package"] = evidence
    result = _authorize(pkg, tmp_path, monkeypatch)
    assert result.authorized is False
    assert any("untrusted_boolean" in b or "user_consent" in b for b in result.blocking_reasons)


def test_verify_trusted_evidence_unit_bindings():
    rec = issue_trusted_evidence(
        claim="posting_open",
        user_id=USER,
        job_key="url:https://example.com/1",
        session_id=SESSION,
        artifact_fingerprint="a" * 64,
        secret=SECRET,
    )
    ok, _ = verify_trusted_evidence(
        rec,
        expected_claim="posting_open",
        user_id=USER,
        job_key="url:https://example.com/1",
        session_id=SESSION,
        artifact_fingerprint="a" * 64,
        secret=SECRET,
    )
    assert ok is True
    bad, reason = verify_trusted_evidence(
        rec,
        expected_claim="posting_open",
        user_id=USER,
        job_key="url:https://example.com/OTHER",
        session_id=SESSION,
        artifact_fingerprint="a" * 64,
        secret=SECRET,
    )
    assert bad is False
    assert reason == "evidence_job_mismatch"
