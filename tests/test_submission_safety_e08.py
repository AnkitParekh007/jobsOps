"""E08 Submission safety — cap=1, lock, no Applied without receipt, uncertain ≠ Applied."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import validate
from ledger import Ledger
from submission_authorize import (
    STATE_MATERIALS_VALIDATED,
    STATE_READY_FOR_APPROVAL,
    STATE_SUBMISSION_AUTHORIZED,
    STATE_UNCERTAIN,
    acquire_form_lock,
    authorize_submission,
    issue_consent_record,
    issue_trusted_evidence,
    record_submission_outcome,
    would_allow_submit,
)

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e08"
TEST_SECRET = b"jobops-test-evidence-secret-e08"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_daily_cap_blocks_authorize(tmp_path: Path):
    data = _load("cap_exhausted.json")
    result = authorize_submission(
        data,
        run_id="e08-cap",
        dry_run=False,
        require_form_lock=False,
        submits_today=int(data["submits_today"]),
        identity_markers=["alex", "candidate"],
    )
    assert result.authorized is False
    assert result.state == STATE_READY_FOR_APPROVAL
    assert any("daily_submit_cap" in b for b in result.blocking_reasons)
    assert would_allow_submit(shortlist_count=3, submits_today=1) is False
    assert would_allow_submit(shortlist_count=3, submits_today=0) is True
    assert would_allow_submit(shortlist_count=0, submits_today=0) is False


def test_form_lock_required(tmp_path: Path, monkeypatch):
    data = _load("lock_missing.json")
    data["evidence_package"] = _independent_evidence(
        job_key=data["job_key"], fingerprint=data["pdf_fingerprint"]
    )
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "1")
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", TEST_SECRET.decode())
    result = authorize_submission(
        data,
        run_id="e08-nolock",
        dry_run=False,
        require_form_lock=True,
        submits_today=0,
        ledger=None,
        identity_markers=["alex", "candidate"],
        consent_auto_submit=True,
    )
    assert result.authorized is False
    assert result.state == STATE_MATERIALS_VALIDATED
    assert any("form_lock" in b for b in result.blocking_reasons)


def _independent_evidence(
    *,
    job_key: str = "url:https://jobs.ashbyhq.com/acme/frontend-nolock",
    fingerprint: str = "lok111bbb222ccc333ddd444eee555fff666aaa111bbb222ccc333ddd444eee5",
    user_id: str = "user-alex",
    session_id: str = "sess-test-1",
    approval_id: str = "approval-test-1",
    secret: bytes = TEST_SECRET,
    **overrides,
):
    """HMAC-signed trusted evidence — self-asserted verified=true is insufficient."""
    claims = (
        "posting_open",
        "not_duplicate",
        "hard_eligibility_met",
        "filenames_correct",
        "required_fields_complete",
        "screening_answers_verified",
        "no_auth_wall",
        "portal_session",
    )
    base: dict = {"user_id": user_id, "session_id": session_id, "approval_id": approval_id}
    for claim in claims:
        base[claim] = issue_trusted_evidence(
            claim=claim,
            user_id=user_id,
            job_key=job_key,
            session_id=session_id,
            artifact_fingerprint=fingerprint,
            secret=secret,
        )
    base["user_consent"] = issue_consent_record(
        user_id=user_id,
        job_key=job_key,
        session_id=session_id,
        artifact_fingerprint=fingerprint,
        approval_id=approval_id,
        secret=secret,
    )
    base.update(overrides)
    return base


def test_form_lock_held_can_authorize(tmp_path: Path, monkeypatch):
    data = _load("lock_missing.json")
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    led.start_run("e08-lock", floor=40, phase="authorize")
    acquire_form_lock(led, canonical_url=data["canonical_url"], run_id="e08-lock")
    data["evidence_package"] = _independent_evidence(
        job_key=data["job_key"], fingerprint=data["pdf_fingerprint"]
    )
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "1")
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", TEST_SECRET.decode())
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "1")
    ev = data["evidence_package"]
    led.record_approval(
        approval_id=str(ev["approval_id"]),
        user_id=str(ev["user_id"]),
        job_key=str(data["job_key"]),
        session_id=str(ev["session_id"]),
        artifact_fingerprint=str(data["pdf_fingerprint"]),
        status="approved",
        run_id="e08-lock",
    )
    result = authorize_submission(
        data,
        run_id="e08-lock",
        dry_run=False,
        require_form_lock=True,
        submits_today=0,
        ledger=led,
        identity_markers=["alex", "candidate"],
        consent_auto_submit=True,
    )
    assert result.authorized is True
    assert result.state == STATE_SUBMISSION_AUTHORIZED
    led.close()


def test_agent_checklist_booleans_are_not_proof(tmp_path: Path, monkeypatch):
    data = _load("lock_missing.json")
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    led.start_run("e08-bool", floor=40, phase="authorize")
    acquire_form_lock(led, canonical_url=data["canonical_url"], run_id="e08-bool")
    # All checklist booleans true + approval_id, but evidence values are bare booleans.
    data["checklist"] = {k: True for k in data["checklist"]}
    data["evidence_package"] = {
        "posting_open": True,  # untrusted bare boolean
        "not_duplicate": True,
        "hard_eligibility_met": True,
        "filenames_correct": True,
        "required_fields_complete": True,
        "screening_answers_verified": True,
        "no_auth_wall": True,
        "portal_session": True,
        "user_consent": True,
        "approval_id": "approval-spoofed",
    }
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "1")
    result = authorize_submission(
        data,
        run_id="e08-bool",
        dry_run=False,
        require_form_lock=True,
        submits_today=0,
        ledger=led,
        identity_markers=["alex", "candidate"],
        consent_auto_submit=True,
    )
    assert result.authorized is False
    assert any("evidence_" in b for b in result.blocking_reasons)
    led.close()


def test_uncertain_never_auto_retry():
    data = _load("uncertain_no_retry.json")
    result = authorize_submission(
        data,
        run_id="e08-unc",
        prior_uncertain=True,
        dry_run=False,
        submits_today=0,
        identity_markers=["alex", "candidate"],
    )
    assert result.state == STATE_UNCERTAIN
    assert result.authorized is False
    assert result.package["retryable"] is False
    assert "no_auto_retry" in result.code or any(
        "uncertain" in b for b in result.blocking_reasons
    )


def test_no_applied_without_receipt():
    data = _load("no_applied_without_receipt.json")
    for case in data["cases"]:
        receipt = record_submission_outcome(
            job_key="url:https://jobs.ashbyhq.com/acme/receipt-1",
            canonical_url="https://jobs.ashbyhq.com/acme/receipt-1",
            run_id="e08-receipt",
            portal_confirmation=case["portal_confirmation"],
            gmail_receipt=case["gmail_receipt"],
            confirmation_url="https://jobs.ashbyhq.com/acme/thanks",
        )
        assert receipt["outcome"] == case["expected_outcome"]
        assert receipt["retryable"] is False
        if case["expected_outcome"] != "Applied":
            assert receipt["outcome"] != "Applied" or case["gmail_receipt"]
        if case["name"] == "neither":
            assert receipt["outcome"] == "SubmissionUncertain"
            assert receipt["outcome"] != "Applied"
        validate(receipt, "submission-receipt.schema.json")


def test_applied_requires_gmail_receipt_schema():
    receipt = record_submission_outcome(
        job_key="url:https://jobs.ashbyhq.com/acme/ok",
        canonical_url="https://jobs.ashbyhq.com/acme/ok",
        run_id="e08-ok",
        portal_confirmation=True,
        gmail_receipt=True,
        gmail_message_id="msg-1",
    )
    assert receipt["outcome"] == "Applied"
    validate(receipt, "submission-receipt.schema.json")
