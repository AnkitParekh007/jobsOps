"""E11 Tracker sync — ledger→Sheets idempotent; no duplicate rows on replay."""
from __future__ import annotations

import json
from pathlib import Path

from drive_artifacts import ensure_batch, ensure_folder_paths
from ledger import Ledger
from sheets_sync import build_sync_plan, plan_from_ledger, replay_row_keys, sync_or_plan

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e11"


def _seed(led: Ledger, run_id: str = "e11-sync") -> None:
    jobs = json.loads((FIX / "ledger_jobs.json").read_text(encoding="utf-8"))["jobs"]
    led.start_run(run_id, floor=0, phase="sync")
    for j in jobs:
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


def test_sync_plan_row_keys_stable():
    jobs = json.loads((FIX / "ledger_jobs.json").read_text(encoding="utf-8"))["jobs"]
    plan1 = build_sync_plan(jobs)
    plan2 = build_sync_plan(jobs)
    assert plan1["row_keys"] == plan2["row_keys"]
    assert len(plan1["row_keys"]) == len(set(plan1["row_keys"]))
    assert plan1["row_keys"] == sorted(plan1["row_keys"])


def test_replay_twice_identical_row_keys(tmp_path: Path):
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    _seed(led)
    out1 = tmp_path / "plan1.json"
    out2 = tmp_path / "plan2.json"
    p1 = sync_or_plan(led, out_path=out1)
    p2 = sync_or_plan(led, out_path=out2, prior_plan_path=out1)
    assert replay_row_keys(p1) == replay_row_keys(p2)
    # Second pass: all updates, zero new inserts (idempotent)
    assert p2["insert_count"] == 0
    assert p2["update_count"] == p1["row_count"]
    assert p1["live_api"] is False
    led.close()


def test_no_duplicate_rows_on_replay():
    jobs = json.loads((FIX / "ledger_jobs.json").read_text(encoding="utf-8"))["jobs"]
    plan = build_sync_plan(jobs)
    keys = plan["row_keys"]
    assert len(keys) == len(set(keys))
    # Replay with prior keys → updates only
    replay = build_sync_plan(jobs, prior_row_keys=set(keys))
    assert replay["insert_count"] == 0
    assert set(replay["row_keys"]) == set(keys)


def test_drive_folders_by_job_key(tmp_path: Path):
    root = tmp_path / "drive"
    meta = ensure_folder_paths(
        job_key="url:https://jobs.ashbyhq.com/sync/one",
        organization="SyncCo",
        role="FDE",
        root=root,
    )
    assert Path(meta["absolute_role_folder"]).is_dir()
    assert meta["live_drive_api"] is False
    jobs = json.loads((FIX / "ledger_jobs.json").read_text(encoding="utf-8"))["jobs"]
    batch = ensure_batch(jobs, root=root)
    assert batch["count"] == 3
    assert batch["live_drive_api"] is False


def test_plan_from_ledger_offline(tmp_path: Path):
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    _seed(led)
    plan = plan_from_ledger(led)
    assert plan["row_count"] == 3
    assert plan["live_api"] is False
    led.close()
