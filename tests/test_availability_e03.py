"""E03 — availability: closed never Eligible; unknown → Needs review."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from verify_jobs import verify_match

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e03"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("closed_posting.json", "Closed"),
        ("unknown_availability.json", "Needs review"),
        ("open_with_sponsor.json", "Eligible"),
    ],
)
def test_availability_decisions(name: str, expected: str):
    data = json.loads((FIX / name).read_text(encoding="utf-8"))
    result = verify_match(data, offline=True)
    assert result.decision["decision"] == expected
    assert result.match_status == expected
    if data.get("must_not_be_eligible"):
        assert result.decision["decision"] != "Eligible"


def test_closed_never_eligible_even_with_sponsor_quote():
    data = json.loads((FIX / "closed_posting.json").read_text(encoding="utf-8"))
    assert "sponsor" in (data.get("sponsorship_quote") or "").lower()
    result = verify_match(data, offline=True)
    assert result.decision["decision"] == "Closed"
    assert result.decision["decision"] != "Eligible"


def test_unknown_needs_review_not_eligible():
    data = json.loads((FIX / "unknown_availability.json").read_text(encoding="utf-8"))
    result = verify_match(data, offline=True)
    assert result.decision["decision"] == "Needs review"
    assert any("availability:unknown" in r for r in result.blocking_reasons)
