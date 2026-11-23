"""E02 — duplicate safety: same requisition must not pass as new."""
from __future__ import annotations

import json
from pathlib import Path

from policy import duplicate_job_key

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e02"


def test_same_requisition_two_urls_zero_passthrough():
    data = json.loads((FIX / "same_requisition_two_urls.json").read_text(encoding="utf-8"))
    verdict = duplicate_job_key(data["urls"], existing_keys=data.get("existing_keys") or [])
    assert not verdict.ok
    assert verdict.code == "duplicate_job_key"
    assert verdict.decision == "Duplicate"


def test_prior_ledger_hit_blocked():
    data = json.loads((FIX / "prior_ledger_hit.json").read_text(encoding="utf-8"))
    verdict = duplicate_job_key(data["urls"], existing_keys=data.get("existing_keys") or [])
    assert not verdict.ok
    assert "duplicate" in verdict.code


def test_distinct_urls_pass():
    verdict = duplicate_job_key(
        [
            "https://jobs.ashbyhq.com/a/111",
            "https://jobs.ashbyhq.com/b/222",
        ]
    )
    assert verdict.ok
