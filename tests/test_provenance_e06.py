"""E06 — provenance: empty reason / missing evidence must fail."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts import ContractError, discovered_job_from_match
from policy import provenance_check

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e06"


def test_missing_reason_fails():
    data = json.loads((FIX / "missing_reason.json").read_text(encoding="utf-8"))
    verdict = provenance_check(data)
    assert not verdict.ok
    assert verdict.code == "missing_reason"
    with pytest.raises(ContractError):
        discovered_job_from_match(data)


def test_missing_evidence_fails():
    data = json.loads((FIX / "missing_evidence_refs.json").read_text(encoding="utf-8"))
    verdict = provenance_check(data)
    assert not verdict.ok
    assert "evidence" in verdict.code


def test_valid_provenance_passes():
    data = json.loads((FIX / "valid_provenance.json").read_text(encoding="utf-8"))
    verdict = provenance_check(data)
    assert verdict.ok
    job = discovered_job_from_match(data, shard_id="fde-de")
    assert job["reason"]
    assert job["evidence_refs"]
