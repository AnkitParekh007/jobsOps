"""E05 — eligibility safety: hard-miss fixtures must never be Eligible."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from policy import eligibility_safety_check, evaluate_match_for_eligibility
from verify_jobs import verify_match

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e05"


@pytest.mark.parametrize(
    "name",
    ["de_c1_german.json", "visa_not_available.json", "relocation_not_sponsorship.json"],
)
def test_hard_miss_never_eligible(name: str):
    data = json.loads((FIX / name).read_text(encoding="utf-8"))
    verdict = evaluate_match_for_eligibility(data)
    assert data.get("must_not_be_eligible") is True
    assert verdict.decision != "Eligible"
    # Proposed Eligible on hard miss must fail the gate.
    assert not verdict.ok or verdict.decision in {"Skipped", "Needs review"}
    safety = eligibility_safety_check(
        country=data["country"],
        status=data["status"],
        reason=data.get("reason", ""),
        posting_text=data.get("posting_text", ""),
        sponsorship_quote=data.get("sponsorship_quote", ""),
    )
    assert safety.decision != "Eligible"
    assert not safety.ok


def test_clean_sponsor_language_can_be_eligible():
    verdict = eligibility_safety_check(
        country="Germany",
        status="Eligible",
        reason="Explicit sponsorship",
        posting_text="We sponsor visas for this Munich role.",
        sponsorship_quote="We sponsor work visas.",
    )
    assert verdict.ok
    assert verdict.decision == "Eligible"


def test_e05_expanded_hard_miss_batch_zero_false_eligible():
    """≥20 real/synthetic hard-miss postings → false Eligible = 0 via verify_jobs."""
    batch = json.loads((FIX / "hard_miss_batch.json").read_text(encoding="utf-8"))
    postings = batch["postings"]
    assert len(postings) >= 20

    false_eligible = []
    non_eligible_with_signal = 0
    non_eligible_n = 0
    for p in postings:
        assert p.get("must_not_be_eligible") is True
        result = verify_match(p, offline=True)
        decision = result.decision["decision"]
        if decision == "Eligible":
            false_eligible.append(p["id"])
        # Policy path also must not approve proposed Eligible.
        safety = eligibility_safety_check(
            country=p["country"],
            status="Eligible",
            reason=p.get("reason", ""),
            posting_text=p.get("posting_text", ""),
            sponsorship_quote=p.get("sponsorship_quote", ""),
        )
        if safety.decision == "Eligible" and safety.ok:
            false_eligible.append(f"policy:{p['id']}")
        if decision != "Eligible":
            non_eligible_n += 1
            if result.blocking_reasons or result.decision.get("evidence_refs"):
                non_eligible_with_signal += 1

    assert false_eligible == [], f"false Eligible on hard-miss fixtures: {false_eligible}"
    assert non_eligible_with_signal / max(non_eligible_n, 1) >= 0.95

