"""F01 run_context unit tests."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import validate
from run_context import build_run_context, write_session_inventory


def test_build_run_context_writes_lock_and_schema(tmp_path: Path):
    db = tmp_path / "jobops.db"
    run_dir = tmp_path / "runs" / "ctx-1"
    run_dir.mkdir(parents=True)
    excl = tmp_path / "exclusion-index.json"
    excl.write_text(
        json.dumps({"canonical_urls": ["https://jobs.example.com/prior"], "count": 1})
        + "\n",
        encoding="utf-8",
    )
    ctx = build_run_context(
        run_id="ctx-1",
        floor=40,
        exclusion_path=excl,
        db_path=db,
        acquire_lock=True,
    )
    validate(ctx, "run-context.schema.json")
    assert ctx["preferences"]["daily_submit_cap"] == 1
    assert ctx["preferences"]["handoff_floor"] == 40
    assert ctx["lock"]["acquired"] is True
    assert ctx["gates"]["discovery_allowed"] is True
    assert ctx["exclusion"]["canonical_url_count"] == 1
    inv = write_session_inventory(run_dir, ctx)
    assert inv.is_file()
    payload = json.loads(inv.read_text(encoding="utf-8"))
    assert payload["session_inventory"]["unknown_allowed"] is True
