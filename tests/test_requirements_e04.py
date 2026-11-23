"""E04 — hard skill/language miss → Skipped; clean sponsor path may be Eligible."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from verify_jobs import verify_match

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e04"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("german_fluent.json", "Skipped"),
        ("python_must_have.json", "Skipped"),
        ("clean_frontend.json", "Eligible"),
    ],
)
def test_requirement_rules(name: str, expected: str):
    data = json.loads((FIX / name).read_text(encoding="utf-8"))
    result = verify_match(data, offline=True)
    assert result.decision["decision"] == expected
    if data.get("must_not_be_eligible"):
        assert result.decision["decision"] != "Eligible"
        assert result.decision.get("hard_miss") is True
        assert result.blocking_reasons


def test_german_fluent_hard_miss_blocking_reason():
    data = json.loads((FIX / "german_fluent.json").read_text(encoding="utf-8"))
    result = verify_match(data, offline=True)
    assert result.decision["decision"] == "Skipped"
    assert any("hard_miss:" in r for r in result.blocking_reasons)


def test_python_must_have_skipped():
    data = json.loads((FIX / "python_must_have.json").read_text(encoding="utf-8"))
    result = verify_match(data, offline=True)
    assert result.decision["decision"] == "Skipped"
    assert result.decision["hard_miss"] is True
