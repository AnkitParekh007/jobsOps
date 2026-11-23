#!/usr/bin/env python3
"""F07 P01 — Inbox Outcome Interpreter: classify Gmail-like messages → OutcomeEvent + reconcile."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import (  # noqa: E402
    POLICY_VERSION,
    job_key_from_url,
    make_envelope,
    normalize_url,
    utc_now_iso,
    validate,
)
from ledger import Ledger  # noqa: E402
from policy import can_transition  # noqa: E402

PRODUCER = "inbox_outcomes"
ARTIFACT_TYPE = "outcome_event"

# Outcome → job status reconciliation targets.
OUTCOME_RECONCILE = {
    "receipt": "Applied",
    "rejection": "Rejected",
    "assessment": "Follow-up due",
    "interview": "Follow-up due",
    "offer": "Needs review",
    "follow_up": "Follow-up due",
    "unknown": None,
}

# Statuses that may be reconciled by P01 (esp. SubmissionUncertain → Applied/Rejected).
RECONCILABLE_PRIORS = frozenset(
    {
        "SubmissionUncertain",
        "Submitting",
        "Submitted",
        "Applied",
        "On hold",
        "Needs review",
        "Follow-up due",
        "Ready for approval",
        "ReadyForApproval",
    }
)

RECEIPT_PATTERNS = [
    re.compile(r"\b(application (received|submitted|confirmation)|we (have )?received your (application|submission))\b", re.I),
    re.compile(r"\bthank you for (applying|your application)\b", re.I),
    re.compile(r"\bapplication confirmation\b", re.I),
    re.compile(r"\byour application (was|has been) (successfully )?submitted\b", re.I),
]
REJECTION_PATTERNS = [
    re.compile(r"\b(unfortunately|regret to inform|not (moving|proceeding)|decided not to)\b", re.I),
    re.compile(r"\b(we (will )?not be (moving|proceeding)|position has been filled)\b", re.I),
    re.compile(r"\brejected\b", re.I),
    re.compile(r"\bother candidates\b", re.I),
]
ASSESSMENT_PATTERNS = [
    re.compile(r"\b(take[- ]home|coding (challenge|test)|assessment|hackerrank|codility)\b", re.I),
    re.compile(r"\bcomplete (the|this) (test|assessment|challenge)\b", re.I),
]
INTERVIEW_PATTERNS = [
    re.compile(r"\b(interview|schedule a call|phone screen|hiring manager)\b", re.I),
    re.compile(r"\b(calendly|book a time|availability for)\b", re.I),
]
OFFER_PATTERNS = [
    re.compile(r"\b(offer (letter|of employment)|pleased to offer|compensation package)\b", re.I),
]


@dataclass
class ClassifyResult:
    outcome: dict[str, Any]
    reconciled: bool = False
    prior_status: Optional[str] = None
    new_status: Optional[str] = None
    skipped_reason: Optional[str] = None
    double_count_blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "reconciled": self.reconciled,
            "prior_status": self.prior_status,
            "new_status": self.new_status,
            "skipped_reason": self.skipped_reason,
            "double_count_blocked": self.double_count_blocked,
        }


def _blob(msg: Mapping[str, Any]) -> str:
    parts = [
        msg.get("subject"),
        msg.get("snippet"),
        msg.get("body"),
        msg.get("label"),
        msg.get("from"),
        msg.get("from_address"),
    ]
    return " ".join(str(p) for p in parts if p)


def classify_message(msg: Mapping[str, Any]) -> tuple[str, str]:
    """Return (outcome_type, confidence) from a Gmail-like message dict."""
    # Explicit fixture override
    explicit = msg.get("outcome_type") or msg.get("expected_outcome")
    if isinstance(explicit, str) and explicit.strip().lower() in OUTCOME_RECONCILE:
        return explicit.strip().lower(), "high"

    text = _blob(msg)
    if any(p.search(text) for p in OFFER_PATTERNS):
        return "offer", "high"
    if any(p.search(text) for p in REJECTION_PATTERNS):
        return "rejection", "high"
    if any(p.search(text) for p in INTERVIEW_PATTERNS):
        return "interview", "high"
    if any(p.search(text) for p in ASSESSMENT_PATTERNS):
        return "assessment", "high"
    if any(p.search(text) for p in RECEIPT_PATTERNS):
        return "receipt", "high"
    return "unknown", "low"


def resolve_job_key(msg: Mapping[str, Any]) -> str:
    if isinstance(msg.get("job_key"), str) and msg["job_key"].strip():
        return msg["job_key"].strip()
    url = msg.get("canonical_url") or msg.get("job_url")
    if isinstance(url, str) and url.startswith("http"):
        return job_key_from_url(url)
    org = (msg.get("organization") or "unknown").strip().lower().replace(" ", "-")
    role = (msg.get("role") or "unknown").strip().lower().replace(" ", "-")
    mid = (msg.get("message_id") or msg.get("id") or "msg").strip()
    return f"inbox:{org}:{role}:{mid}"


def make_outcome_event(
    msg: Mapping[str, Any],
    *,
    outcome_type: Optional[str] = None,
    confidence: Optional[str] = None,
    prior_status: Optional[str] = None,
    reconciled: bool = False,
) -> dict[str, Any]:
    otype, conf = classify_message(msg)
    if outcome_type:
        otype = outcome_type
    if confidence:
        conf = confidence
    job_key = resolve_job_key(msg)
    message_id = str(msg.get("message_id") or msg.get("id") or "")
    if not message_id:
        raise ValueError("message_id required")
    url = msg.get("canonical_url") or msg.get("job_url")
    canonical = normalize_url(url) if isinstance(url, str) and url.startswith("http") else None
    refs = list(msg.get("evidence_refs") or [])
    if message_id and f"gmail:{message_id}" not in refs:
        refs.append(f"gmail:{message_id}")
    if canonical and canonical not in refs:
        refs.append(canonical)

    event = {
        "job_key": job_key,
        "canonical_url": canonical,
        "organization": str(msg.get("organization") or ""),
        "role": str(msg.get("role") or ""),
        "outcome_type": otype,
        "source": str(msg.get("source") or "gmail"),
        "message_id": message_id,
        "thread_id": msg.get("thread_id"),
        "subject": str(msg.get("subject") or ""),
        "snippet": str(msg.get("snippet") or msg.get("body") or "")[:500],
        "from_address": str(msg.get("from_address") or msg.get("from") or ""),
        "received_at": msg.get("received_at") or msg.get("date"),
        "classified_at": utc_now_iso(),
        "confidence": conf,
        "reconcile_to": OUTCOME_RECONCILE.get(otype),
        "prior_status": prior_status,
        "reconciled": reconciled,
        "evidence_refs": refs,
        "blocking_reasons": [],
        "policy_version": POLICY_VERSION,
        "notes": str(msg.get("notes") or ""),
    }
    if event["source"] not in {"gmail", "portal", "fixture", "manual"}:
        event["source"] = "fixture"
    validate(event, "outcome-event.schema.json")
    return event


def _job_row(ledger: Ledger, job_key: str) -> Optional[dict[str, Any]]:
    row = ledger._conn.execute(  # noqa: SLF001 — intentional read helper
        "SELECT job_key, canonical_url, organization, role, status, country, lane FROM jobs WHERE job_key=?",
        (job_key,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def _prior_outcome_message_ids(ledger: Ledger, job_key: str) -> set[str]:
    rows = ledger._conn.execute(  # noqa: SLF001
        "SELECT payload_json FROM artifacts WHERE job_key=? AND artifact_type=?",
        (job_key, ARTIFACT_TYPE),
    ).fetchall()
    ids: set[str] = set()
    for r in rows:
        try:
            payload = json.loads(r["payload_json"])
        except json.JSONDecodeError:
            continue
        mid = payload.get("message_id")
        if mid:
            ids.add(str(mid))
    return ids


def process_message(
    msg: Mapping[str, Any],
    *,
    run_id: str,
    ledger: Optional[Ledger] = None,
    write_ledger: bool = True,
) -> ClassifyResult:
    """Classify one message; optionally reconcile job status and append OutcomeEvent."""
    outcome_type, confidence = classify_message(msg)
    job_key = resolve_job_key(msg)
    prior_status: Optional[str] = None
    job = None
    if ledger is not None:
        job = _job_row(ledger, job_key)
        if job:
            prior_status = str(job["status"])
        # Double-count guard: same message_id already recorded for this job.
        if msg.get("message_id") or msg.get("id"):
            mid = str(msg.get("message_id") or msg.get("id"))
            if mid in _prior_outcome_message_ids(ledger, job_key):
                event = make_outcome_event(
                    msg,
                    outcome_type=outcome_type,
                    confidence=confidence,
                    prior_status=prior_status,
                    reconciled=False,
                )
                event["notes"] = (event.get("notes") or "") + " [duplicate message_id skipped]"
                return ClassifyResult(
                    outcome=event,
                    reconciled=False,
                    prior_status=prior_status,
                    skipped_reason="duplicate_message_id",
                    double_count_blocked=True,
                )

    reconcile_to = OUTCOME_RECONCILE.get(outcome_type)
    reconciled = False
    new_status: Optional[str] = None
    skipped: Optional[str] = None

    if reconcile_to and ledger is not None and write_ledger:
        if prior_status is None:
            # Seed job from message so outcome has a home.
            url = msg.get("canonical_url") or msg.get("job_url") or f"https://inbox.local/{job_key}"
            if not str(url).startswith("http"):
                url = f"https://inbox.local/{job_key}"
            # For uncertain/receipt path without prior row: insert as SubmissionUncertain then reconcile.
            seed_status = "SubmissionUncertain" if outcome_type == "receipt" else "Needs review"
            ledger.transition_job(
                job_key,
                canonical_url=str(url),
                status=seed_status,
                run_id=run_id,
                organization=str(msg.get("organization") or ""),
                role=str(msg.get("role") or ""),
                meta={"seeded_by": "inbox_outcomes"},
            )
            prior_status = seed_status

        if prior_status in RECONCILABLE_PRIORS or prior_status == "SubmissionUncertain":
            verdict = can_transition(prior_status, reconcile_to)
            if verdict.ok or prior_status == reconcile_to:
                url = (
                    (job or {}).get("canonical_url")
                    or msg.get("canonical_url")
                    or msg.get("job_url")
                    or f"https://inbox.local/{job_key}"
                )
                ledger.transition_job(
                    job_key,
                    canonical_url=str(url),
                    status=reconcile_to,
                    run_id=run_id,
                    organization=str(msg.get("organization") or (job or {}).get("organization") or ""),
                    role=str(msg.get("role") or (job or {}).get("role") or ""),
                    meta={
                        "reconciled_by": "inbox_outcomes",
                        "outcome_type": outcome_type,
                        "message_id": str(msg.get("message_id") or msg.get("id") or ""),
                    },
                )
                reconciled = True
                new_status = reconcile_to
            else:
                skipped = f"illegal_transition:{prior_status}->{reconcile_to}"
        else:
            skipped = f"prior_not_reconcilable:{prior_status}"
    elif reconcile_to is None:
        skipped = "unknown_outcome"

    event = make_outcome_event(
        msg,
        outcome_type=outcome_type,
        confidence=confidence,
        prior_status=prior_status,
        reconciled=reconciled,
    )
    if skipped:
        event["blocking_reasons"] = [skipped]
        event["notes"] = (event.get("notes") or "") + f" [{skipped}]"

    if ledger is not None and write_ledger and not skipped == "duplicate_message_id":
        env = make_envelope(
            run_id=run_id,
            producer=PRODUCER,
            artifact_type=ARTIFACT_TYPE,
            payload=event,
            job_key=job_key,
            task_id=f"{run_id}:pipeline:p01:{event['message_id']}",
            evidence_refs=event.get("evidence_refs") or [],
            status=event.get("reconcile_to") or outcome_type,
            blocking_reasons=event.get("blocking_reasons") or [],
        )
        ledger.append_artifact(env)
        ledger.audit(
            "outcome_classified",
            run_id=run_id,
            detail={
                "job_key": job_key,
                "outcome_type": outcome_type,
                "reconciled": reconciled,
                "new_status": new_status,
            },
        )

    return ClassifyResult(
        outcome=event,
        reconciled=reconciled,
        prior_status=prior_status,
        new_status=new_status,
        skipped_reason=skipped,
    )


def process_inbox(
    messages: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    ledger: Optional[Ledger] = None,
    write_ledger: bool = True,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    reconciled = 0
    blocked_dupes = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        cr = process_message(msg, run_id=run_id, ledger=ledger, write_ledger=write_ledger)
        results.append(cr.to_dict())
        otype = cr.outcome.get("outcome_type", "unknown")
        counts[otype] = counts.get(otype, 0) + 1
        if cr.reconciled:
            reconciled += 1
        if cr.double_count_blocked:
            blocked_dupes += 1
    return {
        "ok": True,
        "run_id": run_id,
        "processed": len(results),
        "reconciled": reconciled,
        "double_count_blocked": blocked_dupes,
        "by_type": counts,
        "results": results,
        "policy_version": POLICY_VERSION,
    }


# --- P02–P04 stubs (interfaces only; cheap) ---

def draft_interview_prep(outcome: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
    """P02 stub: interview prep brief placeholder — no auto-send."""
    return {
        "capability": "P02",
        "run_id": run_id,
        "job_key": outcome.get("job_key"),
        "status": "stub",
        "artifacts": ["interview_brief_draft", "star_drafts"],
        "auto_send": False,
        "notes": "Generate brief + STAR drafts into Drive folder when interview OutcomeEvent arrives.",
    }


def draft_followup_reminder(outcome: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
    """P03 stub: follow-up deadline reminder — human sends."""
    return {
        "capability": "P03",
        "run_id": run_id,
        "job_key": outcome.get("job_key"),
        "status": "stub",
        "pending_actions": ["follow_up_draft"],
        "auto_send": False,
        "notes": "Draft reminders; write pending_actions; human sends.",
    }


def draft_offer_comparison(outcome: Mapping[str, Any], *, run_id: str) -> dict[str, Any]:
    """P04 stub: structured offer comparison artifact only."""
    return {
        "capability": "P04",
        "run_id": run_id,
        "job_key": outcome.get("job_key"),
        "status": "stub",
        "artifact": "offer_comparison",
        "notes": "Structured comparison artifact only — no acceptance action.",
    }


def load_messages(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    if isinstance(data, dict):
        msgs = data.get("messages") or data.get("inbox") or []
        return [m for m in msgs if isinstance(m, dict)]
    return []


def _cli() -> int:
    ap = argparse.ArgumentParser(description="P01 Inbox Outcome Interpreter")
    ap.add_argument("--inbox", required=True, help="JSON file with Gmail-like messages")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--db", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true", help="Classify only; no ledger writes")
    args = ap.parse_args()

    messages = load_messages(Path(args.inbox))
    led: Optional[Ledger] = None
    if args.db and not args.dry_run:
        led = Ledger(args.db)
        if not led._conn.execute(  # noqa: SLF001
            "SELECT 1 FROM runs WHERE run_id=?", (args.run_id,)
        ).fetchone():
            led.start_run(args.run_id, floor=0, phase="pipeline")

    try:
        summary = process_inbox(
            messages,
            run_id=args.run_id,
            ledger=led,
            write_ledger=led is not None and not args.dry_run,
        )
        # Attach P02–P04 stubs for interview/offer/follow_up outcomes.
        stubs = []
        for r in summary["results"]:
            o = r["outcome"]
            otype = o.get("outcome_type")
            if otype == "interview":
                stubs.append(draft_interview_prep(o, run_id=args.run_id))
            elif otype == "offer":
                stubs.append(draft_offer_comparison(o, run_id=args.run_id))
            elif otype in {"assessment", "follow_up"}:
                stubs.append(draft_followup_reminder(o, run_id=args.run_id))
        summary["p02_p04_stubs"] = stubs
        if args.out:
            Path(args.out).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        return 0
    finally:
        if led is not None:
            led.close()


if __name__ == "__main__":
    raise SystemExit(_cli())
