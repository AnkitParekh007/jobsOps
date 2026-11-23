"""Adversarial fixtures: injection, India hybrid, post-submit timeout."""
from __future__ import annotations

import json
from pathlib import Path

from policy import (
    evaluate_match_for_eligibility,
    india_remote_exclusion,
    post_submit_timeout_hold,
)

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "adversarial"


def test_prompt_injection_held():
    data = json.loads((FIX / "prompt_injection_jd.json").read_text(encoding="utf-8"))
    verdict = evaluate_match_for_eligibility(data)
    assert not verdict.ok
    assert verdict.code == "prompt_injection"
    assert verdict.decision in {"Needs review", "Skipped", "On hold"}


def test_india_excluded_remote():
    data = json.loads((FIX / "india_excluded_remote.json").read_text(encoding="utf-8"))
    verdict = evaluate_match_for_eligibility(data)
    assert verdict.decision != "Eligible"
    assert not verdict.ok or verdict.decision == "Skipped"
    india = india_remote_exclusion(
        data["country"],
        data.get("work_model", ""),
        data.get("posting_text", ""),
    )
    assert not india.ok
    assert india.decision == "Skipped"


def test_post_submit_timeout_not_applied():
    data = json.loads((FIX / "post_submit_timeout.json").read_text(encoding="utf-8"))
    verdict = post_submit_timeout_hold(
        confirmation_seen=data["confirmation_seen"],
        gmail_receipt=data["gmail_receipt"],
    )
    assert verdict.decision == "On hold"
    assert verdict.decision != "Applied"
    assert not verdict.ok
