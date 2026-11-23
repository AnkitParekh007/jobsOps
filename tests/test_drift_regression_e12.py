"""E12 Drift / regression — golden hard-miss traces must never become Eligible."""
from __future__ import annotations

import json
from pathlib import Path

from policy import eligibility_safety_check, evaluate_match_for_eligibility
from verify_jobs import verify_match

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e12"


def test_golden_hard_miss_never_eligible():
    data = json.loads((FIX / "golden_hard_miss.json").read_text(encoding="utf-8"))
    for case in data["cases"]:
        verdict = eligibility_safety_check(
            country=case["country"],
            status=case["status"],
            reason=case.get("reason") or "",
            posting_text=case.get("posting_text") or "",
            sponsorship_quote=case.get("sponsorship_quote") or "",
        )
        if case["expect_eligible"]:
            assert verdict.ok and (verdict.decision or "").lower() == "eligible", case["name"]
        else:
            # Must not allow Eligible
            assert not (
                verdict.ok and (verdict.decision or case["status"]).lower() == "eligible"
            ) or not verdict.ok, f"regression Eligible: {case['name']}"
            if case["status"].lower() == "eligible":
                assert verdict.ok is False or (verdict.decision or "").lower() != "eligible"


def test_golden_evaluate_match_composite():
    data = json.loads((FIX / "golden_hard_miss.json").read_text(encoding="utf-8"))
    for case in data["cases"]:
        if case["expect_eligible"]:
            continue
        match = {
            "country": case["country"],
            "status": "Eligible",
            "reason": case.get("reason") or "n/a",
            "posting_text": case.get("posting_text") or "",
            "sponsorship_quote": case.get("sponsorship_quote") or "",
            "evidence_refs": ["https://jobs.example.com/golden"],
            "employer_or_ats_url": "https://jobs.example.com/golden",
        }
        verdict = evaluate_match_for_eligibility(match)
        assert verdict.ok is False or (verdict.decision or "").lower() != "eligible", case[
            "name"
        ]


def test_golden_verify_batch_no_false_eligible():
    """Phase 2–3 golden postings: hard misses must not verify as Eligible."""
    batch = json.loads((FIX / "golden_verify_batch.json").read_text(encoding="utf-8"))
    for raw in batch["matches"]:
        result = verify_match(raw, offline=True)
        decision = result.decision["decision"]
        assert decision != "Eligible", raw["canonical_url"]
        assert result.match_status != "Eligible"
