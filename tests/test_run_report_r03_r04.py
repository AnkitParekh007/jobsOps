"""R03/R04 — report metrics enrichment + reliability heuristics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ledger import Ledger
from run_report import (
    build_metrics,
    build_reliability_alerts,
    detect_missing_receipts,
    detect_stuck_locks,
    enrich_report_markdown,
    write_phase4_artifacts,
)


def test_metrics_include_eligible_cap_stubs(tmp_path: Path):
    run_dir = tmp_path / "run"
    shards = run_dir / "shards"
    shards.mkdir(parents=True)
    (shards / "frontend-de.json").write_text(
        '{"shard_id":"frontend-de","matches":[],"notes":"harness stub after worker rc=143",'
        '"sources_tried":["worker-failed-or-empty"]}\n',
        encoding="utf-8",
    )
    metrics = build_metrics(
        run_id="r03-1",
        run_dir=run_dir,
        eligible_count=2,
        verify_summary={"counts": {"Eligible": 2, "Needs review": 5, "Skipped": 3}},
        submits_today=0,
    )
    assert metrics["eligible_count"] == 2
    assert metrics["cap_remaining"] == 1
    assert metrics["stubbed_workers"][0]["shard_id"] == "frontend-de"
    assert metrics["verify"]["eligible"] == 2


def test_stuck_lock_and_missing_receipt_alerts(tmp_path: Path):
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    led.start_run("r04-1", floor=0, phase="test")
    # Manually insert an old open lock + long-pending uncertain job
    old_lock = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat().replace("+00:00", "Z")
    old_job = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat().replace("+00:00", "Z")
    led._conn.execute(
        "INSERT INTO locks(lock_id, resource, run_id, acquired_at, state) VALUES (?,?,?,?,?)",
        ("lock_old", "form:https://jobs.example.com/x", "r04-1", old_lock, "open"),
    )
    led._conn.execute(
        """
        INSERT INTO jobs(job_key, canonical_url, organization, role, status, country, lane,
          first_seen_run_id, last_run_id, updated_at, meta_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "url:https://jobs.example.com/unc",
            "https://jobs.example.com/unc",
            "X",
            "Y",
            "SubmissionUncertain",
            "DE",
            "1",
            "r04-1",
            "r04-1",
            old_job,
            "{}",
        ),
    )
    led._conn.commit()
    stuck = detect_stuck_locks(led, max_hours=6)
    missing = detect_missing_receipts(led, max_hours=24)
    assert len(stuck) == 1
    assert stuck[0]["kind"] == "stuck_lock"
    assert len(missing) == 1
    assert missing[0]["kind"] == "missing_receipt"
    alerts = build_reliability_alerts(run_dir=tmp_path, ledger=led, stuck_lock_hours=6, missing_receipt_hours=24)
    assert alerts["alert_count"] >= 2
    led.close()


def test_enrich_report_appends_metrics_section(tmp_path: Path):
    report = tmp_path / "last-run-report.md"
    report.write_text(
        "# report\n\nno quota was promised, and no unverified submission was recorded\n",
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    summary = write_phase4_artifacts(
        run_id="r03-enrich",
        run_dir=run_dir,
        report_path=report,
        eligible_count=0,
        submits_today=1,
    )
    text = report.read_text(encoding="utf-8")
    assert "Phase 4 metrics" in text
    assert "cap remaining" in text
    assert summary["cap_remaining"] == 0
    # Idempotent enrich
    again = enrich_report_markdown(text, metrics={"eligible_count": 0, "cap_remaining": 0})
    assert again.count("Phase 4 metrics") == 1
