"""Unit tests for lib/verify_jobs.py — V01–V04 + free-text rejection."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts import ContractError, POLICY_VERSION
from ledger import Ledger
from verify_jobs import (
    check_availability,
    parse_agent_eligibility_output,
    verify_handoff_state,
    verify_match,
)


def test_parse_agent_rejects_free_text():
    with pytest.raises(ContractError, match="free text|JSON"):
        parse_agent_eligibility_output(
            "This role looks Eligible because relocation is offered."
        )


def test_parse_agent_rejects_invalid_decision():
    with pytest.raises(ContractError):
        parse_agent_eligibility_output(
            {
                "job_key": "url:https://example.com/1",
                "canonical_url": "https://example.com/1",
                "decision": "Maybe",
                "blocking_reasons": [],
                "evidence_refs": ["https://example.com/1"],
                "policy_version": POLICY_VERSION,
            }
        )


def test_parse_agent_accepts_eligibility_decision():
    raw = {
        "job_key": "url:https://example.com/1",
        "canonical_url": "https://example.com/1",
        "decision": "Needs review",
        "blocking_reasons": ["sponsorship_not_evidenced"],
        "evidence_refs": ["https://example.com/1"],
        "sponsorship_evidence": None,
        "hard_miss": False,
        "policy_version": POLICY_VERSION,
        "notes": "no quote",
    }
    dec = parse_agent_eligibility_output(json.dumps(raw))
    assert dec["decision"] == "Needs review"


def test_v04_exclusion_duplicate():
    match = {
        "canonical_url": "https://jobs.ashbyhq.com/acme/dup-1",
        "employer_or_ats_url": "https://jobs.ashbyhq.com/acme/dup-1",
        "country": "Germany",
        "availability": "open",
        "posting_text": "Visa sponsorship available.",
    }
    result = verify_match(
        match,
        exclusion={"https://jobs.ashbyhq.com/acme/dup-1"},
        offline=True,
    )
    assert result.decision["decision"] == "Duplicate"


def test_v04_ledger_prior_key():
    url = "https://jobs.ashbyhq.com/acme/prior-1"
    match = {
        "canonical_url": url,
        "employer_or_ats_url": url,
        "country": "Ireland",
        "availability": "open",
        "posting_text": "We sponsor visas.",
    }
    from contracts import job_key_from_url

    result = verify_match(
        match,
        prior_keys={job_key_from_url(url)},
        offline=True,
    )
    assert result.decision["decision"] == "Duplicate"


def test_missing_sponsorship_needs_review_never_eligible():
    match = {
        "canonical_url": "https://jobs.ashbyhq.com/acme/nosponsor-1",
        "employer_or_ats_url": "https://jobs.ashbyhq.com/acme/nosponsor-1",
        "country": "Germany",
        "availability": "open",
        "posting_text": "React and TypeScript. Hybrid Berlin.",
        "reason": "no sponsor line",
    }
    result = verify_match(match, offline=True)
    assert result.decision["decision"] == "Needs review"
    assert "sponsorship_not_evidenced" in result.blocking_reasons


def test_check_availability_closed_status():
    def fetch(_url: str):
        return 404, "Not Found"

    avail = check_availability("https://example.com/gone", fetch=fetch)
    assert avail.state == "closed"


def test_check_availability_open():
    def fetch(_url: str):
        return 200, "<html>Senior Engineer — apply now</html>"

    avail = check_availability("https://example.com/open", fetch=fetch)
    assert avail.state == "open"


def test_verify_handoff_enriches_and_ledger(tmp_path: Path):
    state = {
        "run_id": "test-verify-1",
        "floor": 40,
        "cumulative_handoff_matches": 2,
        "floor_met": False,
        "readable_sources_exhausted": False,
        "sources_tried": ["Ashby"],
        "sources_blocked": [],
        "sources_remaining_readable": [],
        "phase": "post-discovery",
        "matches": [
            {
                "canonical_url": "https://jobs.ashbyhq.com/acme/a1",
                "employer_or_ats_url": "https://jobs.ashbyhq.com/acme/a1",
                "organization": "Acme",
                "role": "FDE",
                "status": "Needs review",
                "lane": 1,
                "country": "Germany",
                "source": "Ashby",
                "reason": "checking",
                "availability": "open",
                "posting_text": "Fluent German required. Visa sponsorship available.",
            },
            {
                "canonical_url": "https://jobs.ashbyhq.com/acme/a2",
                "employer_or_ats_url": "https://jobs.ashbyhq.com/acme/a2",
                "organization": "Acme",
                "role": "FE",
                "status": "Needs review",
                "lane": 2,
                "country": "Germany",
                "source": "Ashby",
                "reason": "checking",
                "availability": "open",
                "posting_text": "Visa sponsorship available for this role.",
                "sponsorship_quote": "Visa sponsorship available for this role.",
            },
        ],
    }
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    led.start_run("test-verify-1", floor=40)
    summary = verify_handoff_state(
        state,
        run_id="test-verify-1",
        offline=True,
        ledger=led,
    )
    assert summary["counts"]["Skipped"] == 1
    assert summary["counts"]["Eligible"] == 1
    assert state["matches"][0]["status"] == "Skipped"
    assert state["matches"][1]["status"] == "Eligible"
    assert state["eligible_count"] == 1
    assert "eligibility_decision" in state["matches"][0]

    rows = led._conn.execute(  # noqa: SLF001
        "SELECT artifact_type FROM artifacts WHERE artifact_type='eligibility_decision'"
    ).fetchall()
    assert len(rows) == 2
    led.close()


def test_agent_decision_merge_for_ambiguous():
    match = {
        "canonical_url": "https://jobs.ashbyhq.com/acme/amb-1",
        "employer_or_ats_url": "https://jobs.ashbyhq.com/acme/amb-1",
        "country": "Germany",
        "availability": "open",
        "posting_text": "Please discuss visa or immigration options with recruiting.",
        "reason": "ambiguous",
    }
    from contracts import job_key_from_url, normalize_url

    jk = job_key_from_url(match["canonical_url"])
    agent = {
        jk: {
            "job_key": jk,
            "canonical_url": normalize_url(match["canonical_url"]),
            "decision": "Needs review",
            "blocking_reasons": ["sponsorship_not_evidenced"],
            "evidence_refs": [normalize_url(match["canonical_url"])],
            "sponsorship_evidence": None,
            "hard_miss": False,
            "policy_version": POLICY_VERSION,
            "notes": "agent confirmed no sponsor phrase",
        }
    }
    result = verify_match(match, offline=True, agent_decisions=agent)
    assert result.used_agent is True
    assert result.decision["decision"] == "Needs review"
