"""F01 run_context unit tests."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import validate
from run_context import build_run_context, write_session_inventory
from user_workspace import write_candidate_profile


def test_build_run_context_writes_lock_and_schema(tmp_path: Path):
    db = tmp_path / "jobops.db"
    home = tmp_path / "jobops-home"
    write_candidate_profile(
        {
            "display_name": "Alex Candidate",
            "identity_markers": ["alex", "candidate"],
            "resume_urls": ["https://example.com/resume"],
            "verified_facts": [
                "Synthetic fixture candidate — Angular/React/TypeScript.",
                "Do not invent unverified credentials.",
            ],
            "preferences": {
                "country_priority": ["Germany", "Ireland"],
                "sponsorship_required_countries": ["Germany", "Ireland"],
                "daily_submit_cap": 1,
            },
            "consent": {"auto_submit_enabled": False, "outreach_send_enabled": False},
        },
        home=home,
    )
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
        workspace_home=home,
    )
    validate(ctx, "run-context.schema.json")
    assert ctx["preferences"]["daily_submit_cap"] == 1
    assert ctx["preferences"]["handoff_floor"] == 40
    assert ctx["lock"]["acquired"] is True
    assert ctx["gates"]["discovery_allowed"] is True
    assert ctx["exclusion"]["canonical_url_count"] == 1
    facts_blob = json.dumps(ctx["verified_facts"]).lower()
    assert "ankitparekh007.github.io" not in facts_blob
    assert "ankit77parekh" not in facts_blob
    assert ctx["verified_facts"]["display_name"] == "Alex Candidate"
    assert ctx["verified_facts"]["facts"]
    assert ctx["gates"]["auto_submit_enabled"] is False
    inv = write_session_inventory(run_dir, ctx)
    assert inv.is_file()
    payload = json.loads(inv.read_text(encoding="utf-8"))
    assert payload["session_inventory"]["unknown_allowed"] is True


def test_build_run_context_without_profile_has_no_personal_defaults(tmp_path: Path):
    db = tmp_path / "jobops.db"
    home = tmp_path / "empty-home"
    home.mkdir()
    ctx = build_run_context(
        run_id="ctx-empty",
        floor=40,
        db_path=db,
        workspace_home=home,
        acquire_lock=True,
    )
    assert ctx["verified_facts"]["facts"] == []
    assert ctx["verified_facts"]["source_urls"] == []
    assert ctx["gates"]["auto_submit_enabled"] is False
    assert ctx["gates"]["outreach_send_enabled"] is False
