"""E01 — schema validation for envelopes and core payloads."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts import (
    ContractError,
    discovered_job_from_match,
    make_eligibility_decision,
    make_envelope,
    validate,
    validate_envelope,
)

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e01"


def test_valid_envelope_fixture_passes():
    data = json.loads((FIX / "valid_envelope.json").read_text(encoding="utf-8"))
    validate_envelope(data)


def test_invalid_envelope_fixture_fails():
    data = json.loads((FIX / "invalid_envelope_missing_fields.json").read_text(encoding="utf-8"))
    with pytest.raises(ContractError):
        validate_envelope(data)


def test_make_envelope_round_trip():
    env = make_envelope(
        run_id="test-run",
        producer="unit",
        artifact_type="unit_probe",
        payload={"ok": True},
        evidence_refs=["https://example.com"],
    )
    assert env["schema_version"]
    assert env["event_id"].startswith("evt_")
    validate_envelope(env)


def test_discovered_job_requires_reason():
    with pytest.raises(ContractError):
        discovered_job_from_match(
            {
                "canonical_url": "https://jobs.example.com/1",
                "employer_or_ats_url": "https://jobs.example.com/1",
                "status": "Needs review",
                "reason": "",
            }
        )


def test_discovered_job_valid():
    job = discovered_job_from_match(
        {
            "canonical_url": "https://jobs.example.com/1?utm=x",
            "employer_or_ats_url": "https://jobs.example.com/1",
            "organization": "Ex",
            "role": "FDE",
            "status": "Needs review",
            "lane": 1,
            "country": "Germany",
            "source": "Ashby",
            "reason": "Sponsorship not evidenced",
        },
        shard_id="fde-de",
    )
    assert job["canonical_url"] == "https://jobs.example.com/1"
    assert job["evidence_refs"]


def test_eligibility_decision_eligible_cannot_have_blockers():
    with pytest.raises(ContractError):
        make_eligibility_decision(
            job_key="url:https://jobs.example.com/1",
            canonical_url="https://jobs.example.com/1",
            decision="Eligible",
            blocking_reasons=["hard_miss"],
            hard_miss=True,
        )


def test_run_context_schema_shape():
    # Minimal shape check against schema file existence + envelope coupling.
    schema = json.loads((ROOT / "contracts" / "run-context.schema.json").read_text())
    assert "verified_facts" in schema["required"]
    validate(
        {
            "schema_version": "1.0.0",
            "run_id": "r1",
            "created_at": "2026-11-23T00:00:00Z",
            "policy_version": "jobops-p1-2026-11",
            "verified_facts": {"source_urls": [], "facts": [], "contradictions": []},
            "preferences": {
                "country_priority": ["Germany"],
                "sponsorship_required_countries": ["Germany"],
                "daily_submit_cap": 1,
                "handoff_floor": 40,
            },
            "exclusion": {
                "canonical_url_count": 0,
                "prior_job_key_count": 0,
                "path": None,
            },
            "session_inventory": {"portals": [], "unknown_allowed": True},
            "lock": {"acquired": True, "lock_id": "lock_1"},
        },
        "run-context.schema.json",
    )
