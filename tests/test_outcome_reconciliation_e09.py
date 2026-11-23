"""E09 Outcome reconciliation — uncertain+receipt→Applied; reject→Rejected; no double-count."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import validate
from inbox_outcomes import classify_message, load_messages, process_inbox, process_message
from ledger import Ledger

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e09"


def _seed_prior_jobs(led: Ledger, run_id: str) -> None:
    prior = json.loads((FIX / "prior_uncertain_jobs.json").read_text(encoding="utf-8"))
    led.start_run(run_id, floor=0, phase="pipeline")
    for j in prior["jobs"]:
        led.transition_job(
            j["job_key"],
            canonical_url=j["canonical_url"],
            status=j["status"],
            run_id=run_id,
            organization=j.get("organization") or "",
            role=j.get("role") or "",
            country=j.get("country") or "",
            lane=j.get("lane"),
        )


def test_classify_receipt_reject_interview():
    msgs = load_messages(FIX / "gmail_inbox.json")
    assert classify_message(msgs[0])[0] == "receipt"
    assert classify_message(msgs[1])[0] == "rejection"
    assert classify_message(msgs[2])[0] == "interview"


def test_uncertain_receipt_becomes_applied(tmp_path: Path):
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    run_id = "e09-receipt"
    _seed_prior_jobs(led, run_id)
    msgs = load_messages(FIX / "gmail_inbox.json")
    receipt = msgs[0]
    cr = process_message(receipt, run_id=run_id, ledger=led)
    assert cr.outcome["outcome_type"] == "receipt"
    validate(cr.outcome, "outcome-event.schema.json")
    assert cr.reconciled is True
    assert cr.new_status == "Applied"
    row = led._conn.execute(
        "SELECT status FROM jobs WHERE job_key=?",
        (receipt["job_key"],),
    ).fetchone()
    assert row["status"] == "Applied"
    led.close()


def test_uncertain_reject_becomes_rejected(tmp_path: Path):
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    run_id = "e09-reject"
    _seed_prior_jobs(led, run_id)
    msgs = load_messages(FIX / "gmail_inbox.json")
    reject = msgs[1]
    cr = process_message(reject, run_id=run_id, ledger=led)
    assert cr.outcome["outcome_type"] == "rejection"
    assert cr.reconciled is True
    assert cr.new_status == "Rejected"
    row = led._conn.execute(
        "SELECT status FROM jobs WHERE job_key=?",
        (reject["job_key"],),
    ).fetchone()
    assert row["status"] == "Rejected"
    led.close()


def test_no_double_count_same_message(tmp_path: Path):
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    run_id = "e09-dupe"
    _seed_prior_jobs(led, run_id)
    msgs = load_messages(FIX / "gmail_inbox.json")
    # Full inbox includes duplicate msg-receipt-001 at the end
    summary = process_inbox(msgs, run_id=run_id, ledger=led)
    assert summary["double_count_blocked"] >= 1
    # Applied only once for acme uncertain-1
    arts = led._conn.execute(
        "SELECT COUNT(*) AS c FROM artifacts WHERE job_key=? AND artifact_type='outcome_event'",
        ("url:https://jobs.ashbyhq.com/acme/uncertain-1",),
    ).fetchone()
    # First write only (duplicate blocked before second append)
    assert arts["c"] == 1
    row = led._conn.execute(
        "SELECT status FROM jobs WHERE job_key=?",
        ("url:https://jobs.ashbyhq.com/acme/uncertain-1",),
    ).fetchone()
    assert row["status"] == "Applied"
    led.close()


def test_interview_outcome_event_schema(tmp_path: Path):
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    run_id = "e09-interview"
    _seed_prior_jobs(led, run_id)
    msgs = load_messages(FIX / "gmail_inbox.json")
    cr = process_message(msgs[2], run_id=run_id, ledger=led)
    assert cr.outcome["outcome_type"] == "interview"
    assert cr.outcome["reconcile_to"] == "Follow-up due"
    validate(cr.outcome, "outcome-event.schema.json")
    led.close()
