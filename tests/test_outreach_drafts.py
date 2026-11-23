"""F06 Outreach — drafts only; approval gate; no auto-send."""
from __future__ import annotations

import pytest

from contracts import validate
from outreach_drafts import (
    OutreachSafetyError,
    attempt_auto_send,
    create_drafts,
    mark_approved,
    plan_followup,
    write_outreach_draft,
)


def test_draft_schema_and_no_auto_send():
    draft = write_outreach_draft(
        {
            "job_key": "url:https://jobs.example.com/out-1",
            "canonical_url": "https://jobs.example.com/out-1",
            "organization": "OutCo",
            "role": "FDE",
            "contact_name": "Alex Recruiter",
            "contact_email": "alex@outco.example",
            "contact_source": "https://outco.example/team",
            "contact_verified": True,
            "draft_body": "Hello Alex, interested in the FDE role.",
        },
        run_id="out-1",
    )
    assert draft["status"] == "draft"
    assert draft["auto_send"] is False
    assert draft["approval_required"] is True
    validate(draft, "outreach-draft.schema.json")


def test_unverified_contact_refused():
    with pytest.raises(OutreachSafetyError):
        write_outreach_draft(
            {
                "organization": "NoContact",
                "role": "Eng",
                "contact_name": "Unknown",
                "contact_verified": False,
            },
            run_id="out-2",
        )


def test_auto_send_hard_forbidden():
    draft = write_outreach_draft(
        {
            "organization": "OutCo",
            "role": "FDE",
            "contact_name": "Alex",
            "contact_source": "https://linkedin.com/in/alex-public",
            "contact_verified": True,
            "draft_body": "Hello",
        },
        run_id="out-3",
    )
    approved = mark_approved(draft)
    assert approved["status"] == "approved"
    assert approved["auto_send"] is False
    with pytest.raises(OutreachSafetyError, match="auto-send"):
        attempt_auto_send(approved)


def test_followup_suppressed_on_opt_out():
    plan = plan_followup({"status": "opted_out"})
    assert plan["suppressed"] is True
    assert plan["auto_send"] is False


def test_create_drafts_batch():
    summary = create_drafts(
        [
            {
                "organization": "A",
                "role": "R",
                "contact_name": "C",
                "contact_source": "https://a.example/team",
                "contact_verified": True,
                "draft_body": "Hi",
            },
            {
                "organization": "B",
                "role": "R",
                "contact_verified": False,
            },
        ],
        run_id="out-batch",
        write_ledger=False,
    )
    assert summary["count"] == 1
    assert len(summary["gaps"]) == 1
    assert summary["auto_send"] is False
