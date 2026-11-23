#!/usr/bin/env python3
"""F06 Outreach (O01–O04) — draft-only with approval gate; NEVER auto-send."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import (  # noqa: E402
    POLICY_VERSION,
    make_envelope,
    new_id,
    utc_now_iso,
    validate,
)
from ledger import Ledger  # noqa: E402

PRODUCER = "outreach_drafts"
ARTIFACT_TYPE = "outreach_draft"
MAX_DRAFTS_PER_RUN = 10

# Hard rule — this constant is asserted by tests.
AUTO_SEND = False


class OutreachSafetyError(RuntimeError):
    pass


def research_contact(raw: Mapping[str, Any]) -> dict[str, Any]:
    """O01 — Public verified contacts only."""
    verified = bool(raw.get("contact_verified") or raw.get("verified"))
    source = str(raw.get("contact_source") or raw.get("source") or "")
    if not verified or not source.strip():
        return {
            "ok": False,
            "contact_verified": False,
            "gap": "no_verified_public_contact",
            "notes": "Record the gap; do not invent emails.",
        }
    return {
        "ok": True,
        "contact_name": str(raw.get("contact_name") or raw.get("name") or ""),
        "contact_email": raw.get("contact_email") or raw.get("email"),
        "contact_source": source,
        "contact_verified": True,
    }


def map_referral(raw: Mapping[str, Any]) -> dict[str, Any]:
    """O02 — Genuine prior connections only."""
    if not raw.get("referral"):
        return {"referral": False, "ok": True}
    if not raw.get("consent"):
        return {
            "referral": True,
            "ok": False,
            "gap": "referral_without_consent",
        }
    return {
        "referral": True,
        "ok": True,
        "consent": True,
        "connection_note": str(raw.get("connection_note") or ""),
    }


def write_outreach_draft(
    raw: Mapping[str, Any],
    *,
    run_id: str,
) -> dict[str, Any]:
    """O03 — Personalized draft artifact (status=draft, auto_send=false)."""
    contact = research_contact(raw)
    if not contact.get("ok"):
        raise OutreachSafetyError(contact.get("gap") or "contact_unverified")
    referral = map_referral(raw)
    if referral.get("referral") and not referral.get("ok"):
        raise OutreachSafetyError(referral.get("gap") or "referral_invalid")

    draft = {
        "draft_id": new_id("out_"),
        "job_key": str(raw.get("job_key") or ""),
        "canonical_url": raw.get("canonical_url"),
        "organization": str(raw.get("organization") or ""),
        "role": str(raw.get("role") or ""),
        "contact_name": contact["contact_name"],
        "contact_email": contact.get("contact_email"),
        "contact_source": contact["contact_source"],
        "contact_verified": True,
        "referral": bool(referral.get("referral")),
        "draft_subject": str(
            raw.get("draft_subject")
            or f"Interest — {raw.get('role') or 'role'} at {raw.get('organization') or 'company'}"
        ),
        "draft_body": str(
            raw.get("draft_body")
            or (
                f"Hello {contact['contact_name']},\n\n"
                f"I am writing regarding the {raw.get('role') or 'role'} role "
                f"at {raw.get('organization') or 'your company'}. "
                "Happy to share a brief background and verified materials on request.\n\n"
                "Best regards"
            )
        ),
        "follow_up_due": raw.get("follow_up_due"),
        "status": "draft",
        "auto_send": False,
        "approval_required": True,
        "evidence_refs": list(raw.get("evidence_refs") or [contact["contact_source"]]),
        "policy_version": POLICY_VERSION,
        "notes": str(raw.get("notes") or "Draft only — approval required before any send."),
    }
    if not draft["job_key"]:
        draft["job_key"] = f"outreach:{draft['organization']}:{draft['draft_id']}"
    validate(draft, "outreach-draft.schema.json")
    assert draft["auto_send"] is False
    assert draft["status"] == "draft"
    return draft


def plan_followup(draft: Mapping[str, Any], *, business_days: int = 6) -> dict[str, Any]:
    """O04 — Timed draft queue entry (still draft-only)."""
    status = str(draft.get("status") or "draft")
    if status in {"declined", "opted_out"}:
        return {
            "suppressed": True,
            "reason": status,
            "auto_send": False,
        }
    if status == "sent":
        return {
            "suppressed": False,
            "follow_up_draft": True,
            "business_days": business_days,
            "auto_send": False,
            "notes": "One follow-up draft after 5–7 business days with no reply; human sends.",
        }
    return {
        "suppressed": False,
        "follow_up_draft": False,
        "auto_send": False,
        "notes": "Primary draft still awaiting approval/send by human.",
    }


def mark_approved(draft: Mapping[str, Any]) -> dict[str, Any]:
    """Approval gate: draft → approved. Still does NOT send."""
    out = dict(draft)
    out["status"] = "approved"
    out["auto_send"] = False
    out["approval_required"] = True
    out["notes"] = (out.get("notes") or "") + " [approved — human must send; no auto-send]"
    validate(out, "outreach-draft.schema.json")
    return out


def attempt_auto_send(draft: Mapping[str, Any]) -> None:
    """Hard rule: always refuse auto-send."""
    raise OutreachSafetyError("auto-send is forbidden; drafts only")


def create_drafts(
    candidates: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    ledger: Optional[Ledger] = None,
    write_ledger: bool = True,
    max_drafts: int = MAX_DRAFTS_PER_RUN,
) -> dict[str, Any]:
    drafts = []
    gaps = []
    for raw in candidates[:max_drafts]:
        if not isinstance(raw, dict):
            continue
        try:
            d = write_outreach_draft(raw, run_id=run_id)
            drafts.append(d)
            if ledger is not None and write_ledger:
                env = make_envelope(
                    run_id=run_id,
                    producer=PRODUCER,
                    artifact_type=ARTIFACT_TYPE,
                    payload=d,
                    job_key=d["job_key"],
                    task_id=f"{run_id}:outreach:{d['draft_id']}",
                    evidence_refs=d.get("evidence_refs") or [],
                    status="draft",
                )
                ledger.append_artifact(env)
        except OutreachSafetyError as exc:
            gaps.append({"job_key": raw.get("job_key"), "gap": str(exc)})
    return {
        "ok": True,
        "run_id": run_id,
        "drafts": drafts,
        "gaps": gaps,
        "count": len(drafts),
        "auto_send": False,
        "approval_required": True,
        "created_at": utc_now_iso(),
        "policy_version": POLICY_VERSION,
    }


def _cli() -> int:
    ap = argparse.ArgumentParser(description="F06 Outreach drafts (no auto-send)")
    ap.add_argument("--candidates", required=True, help="JSON list of outreach candidates")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--db", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    candidates = list(raw if isinstance(raw, list) else raw.get("candidates") or [])
    led: Optional[Ledger] = None
    if args.db and not args.dry_run:
        led = Ledger(args.db)
    try:
        summary = create_drafts(
            candidates,
            run_id=args.run_id,
            ledger=led,
            write_ledger=led is not None and not args.dry_run,
        )
        if args.out:
            Path(args.out).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "count": summary["count"],
                    "gaps": len(summary["gaps"]),
                    "auto_send": False,
                },
                indent=2,
            )
        )
        return 0
    finally:
        if led is not None:
            led.close()


if __name__ == "__main__":
    raise SystemExit(_cli())
