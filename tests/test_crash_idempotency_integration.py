"""P1.12 — crash recovery, idempotency, concurrent-run, post-submit-timeout."""
from __future__ import annotations

from pathlib import Path

import pytest

from ledger import Ledger
from sheets_sync import build_sync_plan, sync_or_plan
from submission_authorize import (
    STATE_UNCERTAIN,
    acquire_form_lock,
    authorize_submission,
    issue_consent_record,
    issue_trusted_evidence,
    record_submission_outcome,
)
from user_workspace import write_candidate_profile

_TEST_SECRET = b"jobops-test-evidence-secret-race"


def _trusted_pkg(*, job_key: str, fingerprint: str) -> dict:
    user_id = "user-alex"
    session_id = "sess-race-1"
    approval_id = "ap1"
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
    out: dict = {"user_id": user_id, "session_id": session_id, "approval_id": approval_id}
    for claim in claims:
        out[claim] = issue_trusted_evidence(
            claim=claim,
            user_id=user_id,
            job_key=job_key,
            session_id=session_id,
            artifact_fingerprint=fingerprint,
            secret=_TEST_SECRET,
        )
    out["user_consent"] = issue_consent_record(
        user_id=user_id,
        job_key=job_key,
        session_id=session_id,
        artifact_fingerprint=fingerprint,
        approval_id=approval_id,
        secret=_TEST_SECRET,
    )
    return out


def test_ledger_artifact_append_idempotent_on_replay(tmp_path: Path):
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    led.start_run("crash-1", floor=40, phase="discovery")
    from contracts import make_envelope

    env = make_envelope(
        run_id="crash-1",
        producer="test",
        artifact_type="discovered_job",
        payload={"canonical_url": "https://jobs.ashbyhq.com/acme/1", "status": "Needs review"},
        job_key="url:https://jobs.ashbyhq.com/acme/1",
        task_id="crash-1:job-1",
        evidence_refs=["https://jobs.ashbyhq.com/acme/1"],
    )
    first = led.append_artifact(env)
    second = led.append_artifact(env)  # idempotent duplicate → False
    assert first is True
    assert second is False
    rows = led._conn.execute(  # noqa: SLF001
        "SELECT COUNT(*) AS n FROM artifacts WHERE run_id=?",
        ("crash-1",),
    ).fetchone()
    assert rows["n"] == 1
    led.finish_run("crash-1", status="complete", meta={"eligible_count": 0})
    led.close()

    # Crash recovery: reopen DB and continue another run without corruption.
    led2 = Ledger(db)
    led2.start_run("crash-2", floor=40, phase="discovery")
    led2.finish_run("crash-2", status="complete")
    led2.close()


def test_form_lock_blocks_second_run_authorize(tmp_path: Path, monkeypatch):
    db = tmp_path / "jobops.db"
    url = "https://jobs.ashbyhq.com/acme/race-1"
    fp = "a" * 64
    job_key = f"url:{url}"
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
        "evidence_package": _trusted_pkg(job_key=job_key, fingerprint=fp),
    }
    monkeypatch.setenv("JOBOPS_ALLOW_SUBMIT", "1")
    monkeypatch.setenv("JOBOPS_EVIDENCE_SECRET", _TEST_SECRET.decode())
    monkeypatch.setenv("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "1")

    led1 = Ledger(db)
    led1.start_run("race-1", floor=40, phase="authorize")
    acquire_form_lock(led1, canonical_url=url, run_id="race-1")
    ev = pkg["evidence_package"]
    from trust_boundary import open_orchestrator

    home = tmp_path / "jobops-home"
    home.mkdir(exist_ok=True)
    with open_orchestrator(home, principal="pytest"):
        led1.record_approval(
            approval_id=str(ev["approval_id"]),
            user_id=str(ev["user_id"]),
            job_key=job_key,
            session_id=str(ev["session_id"]),
            artifact_fingerprint=fp,
            status="approved",
            run_id="race-1",
        )
    with open_orchestrator(home, principal="pytest"):
        ok1 = authorize_submission(
            pkg,
            run_id="race-1",
            ledger=led1,
            dry_run=False,
            require_form_lock=True,
            submits_today=0,
            identity_markers=["alex", "candidate"],
            consent_auto_submit=True,
        )
    assert ok1.authorized is True

    led2 = Ledger(db)
    led2.start_run("race-2", floor=40, phase="authorize")
    with pytest.raises(RuntimeError, match="lock held"):
        acquire_form_lock(led2, canonical_url=url, run_id="race-2")
    with open_orchestrator(home, principal="pytest"):
        blocked = authorize_submission(
            pkg,
            run_id="race-2",
            ledger=led2,
            dry_run=False,
            require_form_lock=True,
            submits_today=0,
            identity_markers=["alex", "candidate"],
            consent_auto_submit=True,
        )
    assert blocked.authorized is False
    assert any("form_lock" in b for b in blocked.blocking_reasons)
    led1.close()
    led2.close()


def test_post_submit_timeout_never_applied_and_no_retry(tmp_path: Path):
    receipt = record_submission_outcome(
        job_key="url:https://jobs.ashbyhq.com/acme/timeout-1",
        canonical_url="https://jobs.ashbyhq.com/acme/timeout-1",
        run_id="timeout-1",
        portal_confirmation=False,
        gmail_receipt=False,
    )
    assert receipt["outcome"] == STATE_UNCERTAIN
    assert receipt["retryable"] is False
    result = authorize_submission(
        {
            "canonical_url": "https://jobs.ashbyhq.com/acme/timeout-1",
            "state": STATE_UNCERTAIN,
            "ats_score": 90,
            "quality_score": 85,
            "pdf_fingerprint": "b" * 64,
            "fingerprint_method": "fixture",
            "extracted_text": "Alex Candidate",
        },
        run_id="timeout-1",
        prior_uncertain=True,
        identity_markers=["alex", "candidate"],
    )
    assert result.authorized is False
    assert result.state == STATE_UNCERTAIN


def test_sheets_sync_plan_idempotent_replay(tmp_path: Path):
    jobs = [
        {
            "job_key": "url:https://jobs.ashbyhq.com/acme/1",
            "canonical_url": "https://jobs.ashbyhq.com/acme/1",
            "organization": "Acme",
            "role": "Engineer",
            "status": "Eligible",
        }
    ]
    plan1 = build_sync_plan(jobs)
    plan2 = build_sync_plan(jobs, prior_row_keys=set(plan1["row_keys"]))
    assert plan1["row_keys"] == plan2["row_keys"]
    assert plan1["live_api"] is False
    assert plan1["integration"] == "offline_plan"
    assert plan2["update_count"] == 1
    assert plan2["insert_count"] == 0

    db = tmp_path / "jobops.db"
    led = Ledger(db)
    led.start_run("sync-1", floor=40, phase="sync")
    out = tmp_path / "plan.json"
    p1 = sync_or_plan(led, out_path=out, force_offline=True)
    p2 = sync_or_plan(led, out_path=out, prior_plan_path=out, force_offline=True)
    assert p1["live_api"] is False
    assert "offline" in (p1.get("reason") or "").lower() or p1.get("integration") == "offline_plan"
    assert p2["row_keys"] == p1["row_keys"]
    led.close()


def test_workspace_isolation_and_profile_roundtrip(tmp_path: Path):
    home = tmp_path / "jobops-home"
    path = write_candidate_profile(
        {
            "display_name": "Alex Candidate",
            "identity_markers": ["alex", "candidate"],
            "verified_facts": ["Synthetic fact A"],
            "consent": {"auto_submit_enabled": False},
        },
        home=home,
    )
    assert path.is_file()
    assert home.resolve() != Path(__file__).resolve().parents[1]
    from user_workspace import load_candidate_profile, workspace_status

    profile = load_candidate_profile(home=home)
    assert profile.loaded
    assert profile.consent["auto_submit_enabled"] is False
    status = workspace_status(home)
    assert status["isolation_ok"] is True
