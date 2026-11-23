"""F04 rank_opportunities — I01–I04 deterministic; top-5 shortlist; no fictional certainty."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from contracts import validate
from rank_opportunities import (
    rank_handoff_state,
    rank_opportunities,
    score_ats_keyword_coverage,
    score_interview_opportunity,
    score_profile_fit,
)

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "rank"


def test_rank_shortlist_top5_eligible_only():
    data = json.loads((FIX / "eligible_batch.json").read_text(encoding="utf-8"))
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    result = rank_opportunities(data["matches"], now=now, shortlist_size=5)
    assert result["eligible_count"] == 3
    assert result["needs_review_count"] == 1
    assert len(result["shortlist"]) == 3  # only 3 Eligible
    assert all(r["eligibility_decision"] == "Eligible" for r in result["shortlist"])
    assert all(r["shortlist"] is True for r in result["shortlist"])
    # Skipped never ranked
    keys = {r["job_key"] for r in result["ranked_eligible"]}
    assert "url:https://jobs.ashbyhq.com/acme/skip-1" not in keys
    # Needs review surfaced separately
    assert result["human_review"][0]["eligibility_decision"] == "Needs review"
    # Lane1 DE should outrank lane2 IE / MY on priority
    assert result["shortlist"][0]["country"] == "Germany"
    assert result["shortlist"][0]["lane"] == 1
    for r in result["shortlist"]:
        validate(r, "ranked-opportunity.schema.json")
        note = r["score_breakdown"]["certainty_note"].lower()
        assert "fictional" in note or "no fictional" in note
        assert "certainty" in note


def test_i02_transparent_overlap_not_percent_certainty():
    cov, matched, missing, meta = score_ats_keyword_coverage(
        "React TypeScript Python Kubernetes Angular enterprise",
        "react typescript angular enterprise",
    )
    assert 0 <= cov <= 100
    assert "react" in matched or "typescript" in matched
    assert isinstance(meta.get("requirement_term_count"), int)


def test_i03_unknowns_are_zero_no_rescale():
    score, unknowns, bd = score_interview_opportunity(
        posting_text="React TypeScript senior engineer",
        posting_date=None,
        eligibility="Needs review",
        country="Germany",
    )
    assert "posting_date" in unknowns
    assert bd["components"]["freshness"] == 0.0
    assert bd["components"]["recruiter_referral"] == 0.0
    assert bd["components"]["compensation"] == 0.0
    # Total is sum of components — no rescale
    assert score == sum(bd["components"].values())


def test_i01_profile_fit_uses_verified_skills():
    score, gaps, bd = score_profile_fit(
        posting_text="Senior React TypeScript Angular RAG agentic engineer. Visa sponsorship available.",
        sponsorship_evidence="Visa sponsorship available",
        country="Germany",
        eligibility="Eligible",
    )
    assert score >= 50
    assert bd["components"]["skills"] > 0


def test_rank_handoff_writes_artifact_fields():
    data = json.loads((FIX / "eligible_batch.json").read_text(encoding="utf-8"))
    state = {
        "run_id": "fixture-rank",
        "phase": "post-discovery",
        "floor": 40,
        "cumulative_handoff_matches": len(data["matches"]),
        "floor_met": False,
        "matches": data["matches"],
    }
    artifact = rank_handoff_state(state, run_id="fixture-rank")
    assert "shortlist" in artifact
    assert state["ranking"]["shortlist_count"] == len(artifact["shortlist"])
    # Enrichment on Eligible matches
    enriched = [m for m in state["matches"] if m.get("shortlist")]
    assert len(enriched) == len(artifact["shortlist"])
