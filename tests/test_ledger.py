"""Unit tests for SQLite ledger helpers."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import make_envelope
from ledger import Ledger


def test_start_run_lock_and_artifacts(tmp_path: Path):
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    try:
        led.start_run("run-a", floor=40)
        lid = led.acquire_lock("run:run-a", "run-a")
        assert lid
        # Same run re-acquire is idempotent.
        assert led.acquire_lock("run:run-a", "run-a") == lid

        env = make_envelope(
            run_id="run-a",
            producer="test",
            artifact_type="unit",
            payload={"n": 1},
            job_key="url:https://jobs.example.com/1",
        )
        assert led.append_artifact(env) is True
        # Idempotent on same job_key+type+hash
        env2 = dict(env)
        env2["event_id"] = "evt_other"
        assert led.append_artifact(env2) is False

        led.transition_job(
            "url:https://jobs.example.com/1",
            canonical_url="https://jobs.example.com/1",
            status="Needs review",
            run_id="run-a",
            organization="Ex",
            role="FDE",
            country="Germany",
            lane=1,
        )
        assert led.job_key_exists("url:https://jobs.example.com/1")
        assert "url:https://jobs.example.com/1" in led.prior_job_keys()

        led.mark_task("run-a:context", "run-a", "context", "complete", finished=True)
        assert led.is_task_complete("run-a:context")
        assert "context" in led.completed_stages("run-a")

        led.release_lock("run:run-a", run_id="run-a")
        led.finish_run("run-a", status="complete", meta={"eligible_count": 0})
    finally:
        led.close()


def test_ingest_shard_file(tmp_path: Path):
    db = tmp_path / "jobops.db"
    shard = tmp_path / "fde-de.json"
    shard.write_text(
        json.dumps(
            {
                "shard_id": "fde-de",
                "run_id": "run-b",
                "matches": [
                    {
                        "canonical_url": "https://jobs.example.com/abc",
                        "employer_or_ats_url": "https://jobs.example.com/abc",
                        "organization": "Ex",
                        "role": "FDE",
                        "status": "Needs review",
                        "lane": 1,
                        "country": "Germany",
                        "source": "Ashby",
                        "reason": "Sponsorship not evidenced",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    led = Ledger(db)
    try:
        led.start_run("run-b", floor=40)
        summary = led.ingest_shard_file(shard, run_id="run-b")
        assert summary["inserted"] == 1
        assert led.job_key_exists("url:https://jobs.example.com/abc")
    finally:
        led.close()


def test_cross_run_lock_conflict(tmp_path: Path):
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    try:
        led.start_run("run-1", floor=40)
        led.start_run("run-2", floor=40)
        led.acquire_lock("shared-resource", "run-1")
        try:
            led.acquire_lock("shared-resource", "run-2")
            raised = False
        except RuntimeError:
            raised = True
        assert raised
    finally:
        led.close()
