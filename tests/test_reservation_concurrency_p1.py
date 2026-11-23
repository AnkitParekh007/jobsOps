"""
P1 reservation + cross-process concurrency acceptance tests.
"""
from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

from authority import reset_control_plane_for_tests
from ledger import Ledger
from submission_authorize import (
    STATE_SUBMISSION_AUTHORIZED,
    STATE_UNCERTAIN,
    acquire_form_lock,
    authorize_submission,
    form_lock_resource,
    issue_consent_record,
    issue_trusted_evidence,
    record_submission_outcome,
    reserve_daily_submission,
)
from trust_boundary import open_orchestrator

SECRET = b"jobops-reservation-concurrency-secret"
USER = "user-res"
SESSION = "sess-res"
APPROVAL = "approval-res"


def _evidence(job_key: str, fingerprint: str) -> dict:
    claims = [
        "posting_open",
        "not_duplicate",
        "hard_eligibility_met",
        "filenames_correct",
        "required_fields_complete",
        "screening_answers_verified",
        "no_auth_wall",
        "portal_session",
    ]
    out = {
        "user_id": USER,
        "session_id": SESSION,
        "approval_id": APPROVAL,
        "issuer": "jobops.test",
    }
    for claim in claims:
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


def _worker_reserve(args: tuple) -> tuple[bool, str]:
    db, home, i, today = args
    import os

    from authority import install_control_plane_privilege

    os.environ["JOBOPS_CONTROL_PLANE"] = "1"
    os.environ["JOBOPS_ALLOW_TEST_CONTROL_PLANE_RESET"] = "1"
    os.environ.pop("JOBOPS_AGENT_ROLE", None)
    reset_control_plane_for_tests()
    install_control_plane_privilege(Path(home))
    led = Ledger(db)
    try:
        with open_orchestrator(Path(home), principal=f"proc-{i}"):
            ok, reason, _ = reserve_daily_submission(
                led,
                job_key=f"job:proc:{i}",
                run_id=f"run-proc-{i}",
                cap=1,
                submit_date=today,
                reservation_id=f"res-proc-{i}",
            )
        return ok, reason
    finally:
        led.close()


def test_cross_process_daily_cap(jobops_home: Path, monkeypatch):
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    db = str(jobops_home / "state" / "xproc.db")
    home = str(jobops_home)
    today = "2099-06-01"
    # Ensure schema + authority/confirmation keys exist before workers attach.
    from authority import bootstrap_control_plane

    reset_control_plane_for_tests()
    bootstrap_control_plane(jobops_home)
    led = Ledger(db)
    led.close()

    with mp.get_context("spawn").Pool(processes=4) as pool:
        results = pool.map(
            _worker_reserve,
            [(db, home, i, today) for i in range(6)],
        )
    successes = [r for r in results if r[0]]
    failures = [r for r in results if not r[0]]
    assert len(successes) == 1
    assert len(failures) == 5


def test_authorize_requires_reservation_and_consumes_on_applied(
    jobops_home: Path, monkeypatch
):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "1")
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "1")
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)

    url = "https://jobs.ashbyhq.com/acme/res-1"
    job_key = f"url:{url}"
    fp = "e" * 64
    led = Ledger(jobops_home / "state" / "authz.db")
    led.start_run("authz-1", floor=40)
    acquire_form_lock(led, canonical_url=url, run_id="authz-1")
    pkg = {
        "canonical_url": url,
        "job_key": job_key,
        "organization": "Acme",
        "role": "Engineer",
        "ats_score": 90,
        "quality_score": 85,
        "pdf_fingerprint": fp,
        "ats_score_fingerprint": fp,
        "quality_score_fingerprint": fp,
        "fingerprint_method": "fixture",
        "extracted_text": "Alex Candidate\nAngular React TypeScript",
        "evidence_package": _evidence(job_key, fp),
    }

    # Without orchestrator context → not authorized.
    with open_orchestrator(jobops_home, principal="pytest"):
        led.record_approval(
            approval_id=APPROVAL,
            user_id=USER,
            job_key=job_key,
            session_id=SESSION,
            artifact_fingerprint=fp,
            status="approved",
            run_id="authz-1",
            allow_overwrite=True,
        )
    outside = authorize_submission(
        pkg,
        run_id="authz-1",
        ledger=led,
        dry_run=False,
        require_form_lock=True,
        submits_today=0,
        identity_markers=["alex", "candidate"],
        consent_auto_submit=True,
    )
    assert outside.authorized is False
    assert any("reservation" in b for b in outside.blocking_reasons)

    with open_orchestrator(jobops_home, principal="pytest"):
        ok = authorize_submission(
            pkg,
            run_id="authz-1",
            ledger=led,
            dry_run=False,
            require_form_lock=True,
            submits_today=0,
            identity_markers=["alex", "candidate"],
            consent_auto_submit=True,
        )
    assert ok.authorized is True
    assert ok.state == STATE_SUBMISSION_AUTHORIZED
    res_id = (ok.package.get("daily_cap") or {}).get("reservation_id")
    assert res_id
    row = led.get_submission_reservation(res_id)
    assert row is not None
    assert row["state"] == "reserved"

    receipt = record_submission_outcome(
        job_key=job_key,
        canonical_url=url,
        run_id="authz-1",
        portal_confirmation=True,
        gmail_receipt=True,
        confirmation_url=url + "/confirm",
        gmail_message_id="msg-1",
        pdf_fingerprint=fp,
        ledger=led,
        reservation_id=res_id,
    )
    assert receipt["outcome"] == "Applied"
    assert led.get_submission_reservation(res_id)["state"] == "consumed"
    led.close()


def test_uncertain_outcome_marks_reservation_no_retry(jobops_home: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "1")
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "1")
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)

    url = "https://jobs.ashbyhq.com/acme/res-unc"
    job_key = f"url:{url}"
    fp = "f" * 64
    led = Ledger(jobops_home / "state" / "unc.db")
    led.start_run("unc-1", floor=40)
    acquire_form_lock(led, canonical_url=url, run_id="unc-1")
    pkg = {
        "canonical_url": url,
        "job_key": job_key,
        "organization": "Acme",
        "role": "Engineer",
        "ats_score": 90,
        "quality_score": 85,
        "pdf_fingerprint": fp,
        "ats_score_fingerprint": fp,
        "quality_score_fingerprint": fp,
        "fingerprint_method": "fixture",
        "extracted_text": "Alex Candidate\nAngular React TypeScript",
        "evidence_package": _evidence(job_key, fp),
    }
    with open_orchestrator(jobops_home, principal="pytest"):
        led.record_approval(
            approval_id=APPROVAL,
            user_id=USER,
            job_key=job_key,
            session_id=SESSION,
            artifact_fingerprint=fp,
            status="approved",
            run_id="unc-1",
            allow_overwrite=True,
        )
        ok = authorize_submission(
            pkg,
            run_id="unc-1",
            ledger=led,
            dry_run=False,
            require_form_lock=True,
            submits_today=0,
            identity_markers=["alex", "candidate"],
            consent_auto_submit=True,
        )
    assert ok.authorized is True
    res_id = (ok.package.get("daily_cap") or {}).get("reservation_id")
    receipt = record_submission_outcome(
        job_key=job_key,
        canonical_url=url,
        run_id="unc-1",
        portal_confirmation=False,
        gmail_receipt=False,
        ledger=led,
        reservation_id=res_id,
    )
    assert receipt["outcome"] == STATE_UNCERTAIN
    assert led.get_submission_reservation(res_id)["state"] == "uncertain"

    led.release_lock(form_lock_resource(url), run_id="unc-1")
    led.start_run("unc-2", floor=40)
    acquire_form_lock(led, canonical_url=url, run_id="unc-2")
    with open_orchestrator(jobops_home, principal="pytest"):
        retry = authorize_submission(
            pkg,
            run_id="unc-2",
            ledger=led,
            dry_run=False,
            require_form_lock=True,
            identity_markers=["alex", "candidate"],
            consent_auto_submit=True,
        )
    assert retry.authorized is False
    assert any("uncertain" in b for b in retry.blocking_reasons) or retry.state == STATE_UNCERTAIN
    led.close()


def _worker_authorize(args: tuple) -> bool:
    db, home, i = args
    import os

    from authority import install_control_plane_privilege

    os.environ["JOBOPS_CONTROL_PLANE"] = "1"
    os.environ["JOBOPS_ALLOW_TEST_CONTROL_PLANE_RESET"] = "1"
    os.environ["JOBOPS_EVIDENCE_SECRET"] = SECRET.decode()
    os.environ["JOBOPS_ALLOW_SUBMIT"] = "1"
    os.environ["JOBOPS_ALLOW_FIXTURE_EVIDENCE"] = "1"
    os.environ.pop("JOBOPS_AGENT_ROLE", None)
    reset_control_plane_for_tests()
    install_control_plane_privilege(Path(home))

    url = f"https://jobs.ashbyhq.com/acme/conc-{i}"
    job_key = f"url:{url}"
    fp = "a" * 64
    led = Ledger(db)
    try:
        led.start_run(f"conc-{i}", floor=40)
        try:
            acquire_form_lock(led, canonical_url=url, run_id=f"conc-{i}")
        except RuntimeError:
            return False
        with open_orchestrator(Path(home), principal=f"conc-{i}"):
            led.record_approval(
                approval_id=f"appr-{i}",
                user_id=USER,
                job_key=job_key,
                session_id=SESSION,
                artifact_fingerprint=fp,
                status="approved",
                run_id=f"conc-{i}",
                allow_overwrite=True,
            )
            # Unique approval id in evidence
            ev = _evidence(job_key, fp)
            ev["approval_id"] = f"appr-{i}"
            ev["user_consent"] = issue_consent_record(
                user_id=USER,
                job_key=job_key,
                session_id=SESSION,
                artifact_fingerprint=fp,
                approval_id=f"appr-{i}",
                secret=SECRET,
            )
            pkg = {
                "canonical_url": url,
                "job_key": job_key,
                "organization": "Acme",
                "role": "Engineer",
                "ats_score": 90,
                "quality_score": 85,
                "pdf_fingerprint": fp,
                "ats_score_fingerprint": fp,
                "quality_score_fingerprint": fp,
                "fingerprint_method": "fixture",
                "extracted_text": "Alex Candidate\nAngular React TypeScript",
                "evidence_package": ev,
            }
            result = authorize_submission(
                pkg,
                run_id=f"conc-{i}",
                ledger=led,
                dry_run=False,
                require_form_lock=True,
                identity_markers=["alex", "candidate"],
                consent_auto_submit=True,
            )
        return bool(result.authorized)
    finally:
        led.close()


def test_cross_process_authorize_daily_cap(jobops_home: Path, monkeypatch):
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", SECRET.decode())
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "1")
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "1")
    db = str(jobops_home / "state" / "authz-xproc.db")
    home = str(jobops_home)
    from authority import bootstrap_control_plane

    reset_control_plane_for_tests()
    bootstrap_control_plane(jobops_home)
    Ledger(db).close()

    with mp.get_context("spawn").Pool(processes=4) as pool:
        results = pool.map(_worker_authorize, [(db, home, i) for i in range(4)])
    assert sum(1 for r in results if r) == 1
    assert sum(1 for r in results if not r) == 3


def test_permanent_application_identity_blocks_across_dates(
    jobops_home: Path, monkeypatch
):
    """P1: consumed job identity cannot be reserved again on a later date/run."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    led = Ledger(jobops_home / "state" / "ident.db")
    led.start_run("id-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ok, reason, rid = reserve_daily_submission(
            led,
            job_key="job:permanent",
            run_id="id-1",
            cap=5,
            submit_date="2099-01-01",
            reservation_id="res-id-1",
        )
        assert ok is True
        led.consume_submission_reservation(rid, run_id="id-1", job_key="job:permanent")
        blocked, why = led.has_blocking_application_identity("job:permanent")
        assert blocked is True
        assert "consumed" in why
        ok2, reason2, _ = reserve_daily_submission(
            led,
            job_key="job:permanent",
            run_id="id-2",
            cap=5,
            submit_date="2099-01-02",
            reservation_id="res-id-2",
        )
        assert ok2 is False
        assert "application_identity" in reason2 or "consumed" in reason2
    led.close()
