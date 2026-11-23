"""
Reproducible mock-portal E2E (no live network / no real ATS submit).

Simulates: materials → durable approval → trusted evidence → authorize →
receipt outcomes (Applied / blocked / uncertain / duplicate).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from evidence_issuer import TrustedEvidenceIssuer
from ledger import Ledger
from submission_authorize import (
    STATE_READY_FOR_APPROVAL,
    STATE_SUBMISSION_AUTHORIZED,
    STATE_UNCERTAIN,
    acquire_form_lock,
    authorize_submission,
    fingerprint_bytes,
    record_submission_outcome,
)
from trust_boundary import open_orchestrator

SECRET = b"jobops-mock-portal-e2e-secret"
USER = "user-mock"
SESSION = "sess-mock-portal"
APPROVAL = "approval-mock-1"


def _minimal_pdf(path: Path) -> str:
    raw = b"%PDF-1.4\n% mock portal fixture\n" + b"0" * 200 + b"\n%%EOF\n"
    path.write_bytes(raw)
    return fingerprint_bytes(raw)


def test_mock_portal_happy_path_authorize_and_receipt(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "1")
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "0")
    monkeypatch.setenv("JOBOPS_ENABLE_LIVE_SUBMIT", "0")
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)

    pdf = tmp_path / "Alex_Candidate_Acme_Engineer.pdf"
    fp = _minimal_pdf(pdf)
    url = "https://jobs.ashbyhq.com/acme/mock-portal-1"
    job_key = f"url:{url}"

    home = tmp_path / "jobops-home"
    home.mkdir()
    led = Ledger(tmp_path / "mock.db")
    led.start_run("mock-e2e", floor=40, phase="authorize")
    acquire_form_lock(led, canonical_url=url, run_id="mock-e2e")
    with open_orchestrator(home, principal="pytest"):
        led.record_approval(
            approval_id=APPROVAL,
            user_id=USER,
            job_key=job_key,
            session_id=SESSION,
            artifact_fingerprint=fp,
            document_path=str(pdf),
            status="approved",
            run_id="mock-e2e",
            decided_by="user",
        )
        issuer = TrustedEvidenceIssuer(led, secret=SECRET)
        evidence = issuer.issue_package(
            approval_id=APPROVAL,
            user_id=USER,
            job_key=job_key,
            session_id=SESSION,
            artifact_fingerprint=fp,
        )

        result = authorize_submission(
            {
                "canonical_url": url,
                "job_key": job_key,
                "organization": "Acme",
                "role": "Engineer",
                "ats_score": 92,
                "quality_score": 88,
                "pdf_path": str(pdf),
                "pdf_fingerprint": fp,
                "ats_score_fingerprint": fp,
                "quality_score_fingerprint": fp,
                "fingerprint_method": "sha256_bytes",
                "extracted_text": "Alex Candidate\nAngular React TypeScript",
                "evidence_package": evidence,
            },
            run_id="mock-e2e",
            ledger=led,
            dry_run=False,
            require_form_lock=True,
            submits_today=0,
            identity_markers=["alex", "candidate"],
            consent_auto_submit=True,
        )
    assert result.authorized is True
    assert result.state == STATE_SUBMISSION_AUTHORIZED

    res_id = (result.package.get("daily_cap") or {}).get("reservation_id") or (
        (result.package.get("evidence_package") or {}).get("reservation_id")
    )
    receipt = record_submission_outcome(
        job_key=job_key,
        canonical_url=url,
        run_id="mock-e2e",
        portal_confirmation=True,
        gmail_receipt=True,
        confirmation_url="https://jobs.ashbyhq.com/acme/mock-portal-1/confirm",
        gmail_message_id="msg-mock-1",
        pdf_fingerprint=fp,
        ledger=led,
        reservation_id=res_id,
    )
    assert receipt["outcome"] == "Applied"
    led.close()


def test_mock_portal_uncertain_and_duplicate_blocked(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "1")

    uncertain = record_submission_outcome(
        job_key="url:https://jobs.ashbyhq.com/acme/uncertain",
        canonical_url="https://jobs.ashbyhq.com/acme/uncertain",
        run_id="mock-unc",
        portal_confirmation=False,
        gmail_receipt=False,
    )
    assert uncertain["outcome"] == STATE_UNCERTAIN
    assert uncertain["retryable"] is False

    # Prior uncertain cannot auto-retry.
    blocked = authorize_submission(
        {
            "canonical_url": "https://jobs.ashbyhq.com/acme/uncertain",
            "state": STATE_UNCERTAIN,
            "ats_score": 90,
            "quality_score": 85,
            "pdf_fingerprint": "b" * 64,
            "fingerprint_method": "fixture",
            "extracted_text": "Alex Candidate",
        },
        run_id="mock-unc-retry",
        prior_uncertain=True,
        identity_markers=["alex", "candidate"],
    )
    assert blocked.authorized is False
    assert blocked.state == STATE_UNCERTAIN

    # Cap / ready path without submit.
    ready = authorize_submission(
        {
            "canonical_url": "https://jobs.ashbyhq.com/acme/cap",
            "ats_score": 90,
            "quality_score": 85,
            "pdf_fingerprint": "c" * 64,
            "ats_score_fingerprint": "c" * 64,
            "quality_score_fingerprint": "c" * 64,
            "fingerprint_method": "fixture",
            "extracted_text": "Alex Candidate React",
        },
        run_id="mock-cap",
        dry_run=True,
        require_form_lock=False,
        submits_today=1,
        identity_markers=["alex", "candidate"],
    )
    assert ready.authorized is False
    assert ready.state in {STATE_READY_FOR_APPROVAL, "Preparing"}


def test_mock_portal_preview_is_non_mutating(tmp_path: Path, capsys):
    from jobops.cli import main

    before = list(tmp_path.iterdir()) if tmp_path.exists() else []
    rc = main(["run", "--workflow", "discovery", "--preview", "--workspace", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"preview": true' in out or '"mode": "preview"' in out
    assert '"mutating": false' in out
    assert '"invoked_harness": false' in out
    # Preview must not create harness run artifacts under tmp workspace.
    after = list(tmp_path.iterdir()) if tmp_path.exists() else []
    # init-like files may exist from workspace flag only if ensure_workspace called — preview does not.
    assert after == before or not any("runs" in str(p) for p in after)


def test_mock_ats_browser_journey_form_confirm_timeout_duplicate():
    from mock_ats_portal import MockAtsError, MockAtsPortal

    portal = MockAtsPortal(job_url="https://jobs.ashbyhq.com/acme/mock-browser", confirm_timeout_sec=1.0)
    portal.open_form()
    portal.fill_field("name", "Alex Candidate")
    portal.fill_field("email", "alex@example.test")
    portal.fill_field("resume", "Alex_Candidate_Acme.pdf")
    conf = portal.submit()
    assert conf["ok"] and conf["confirmation_id"]
    with pytest.raises(MockAtsError, match="duplicate"):
        portal.open_form()

    timed = MockAtsPortal(confirm_timeout_sec=0.0)
    timed.open_form()
    for field, value in (("name", "Alex"), ("email", "a@b.c"), ("resume", "r.pdf")):
        timed.fill_field(field, value)
    timed.submit(force_timeout=True)
    outcome = timed.await_confirmation(timeout_sec=0.0)
    assert outcome["outcome"] == "SubmissionUncertain"
    assert outcome["retryable"] is False
