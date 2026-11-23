#!/usr/bin/env python3
"""JobOps policy gates: verified facts, tool permissions, caps, status transitions."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import POLICY_VERSION, job_key_from_url, normalize_url  # noqa: E402

DAILY_SUBMIT_CAP = 1
HANDOFF_FLOOR_DEFAULT = 40

COUNTRY_PRIORITY = [
    "Germany",
    "Ireland",
    "UAE",
    "Malaysia",
    "Singapore",
    "India",
]

SPONSORSHIP_REQUIRED = {"Germany", "Ireland", "UAE", "DE", "IE", "AE"}

# Skills / claims that must never be invented.
VERIFIED_FACT_DENYLIST = (
    "python proficiency",
    "expert in python",
    "fluent german",
    "native german",
    "c1 german",
    "german c1",
    "current eu blue card",
    "holds german work authorization",
)

# Patterns that indicate a hard eligibility miss (never Eligible).
HARD_MISS_PATTERNS = [
    re.compile(r"\bgerman\s*(c1|c2|native|fluent|essential|required|mandatory)\b", re.I),
    re.compile(r"\b(fluent|native|essential|required|mandatory)\s+german\b", re.I),
    re.compile(r"\bnative[- ]level german\b", re.I),
    re.compile(r"\bprofessional german\b", re.I),
    re.compile(r"\bvisa sponsorship is not available\b", re.I),
    re.compile(r"\bno visa sponsorship\b", re.I),
    re.compile(r"\bsponsorship not available\b", re.I),
    re.compile(r"\bmust[- ]have python\b", re.I),
    re.compile(r"\bpython (required|mandatory|must[- ]have)\b", re.I),
]

# Relocation language is not sponsorship evidence.
RELOCATION_NOT_SPONSORSHIP = re.compile(
    r"\b(relocation( support| assistance| package)?|willing to relocate|relocate)\b",
    re.I,
)

SPONSORSHIP_EVIDENCE = re.compile(
    r"\b(visa sponsorship|sponsor(s|ship)? (available|provided|offered)|we sponsor)\b",
    re.I,
)

# SOP §15 allowed statuses and a conservative transition graph for Phase 1.
ALLOWED_STATUSES = frozenset(
    {
        "New",
        "Eligible",
        "In preparation",
        "Ready for approval",
        "Submitted",
        "Applied",
        "On hold",
        "Skipped",
        "Rejected",
        "Closed",
        "Duplicate",
        "Follow-up due",
        "Needs review",
        # Phase 3 application-package states (mapped alongside SOP §15)
        "Preparing",
        "MaterialsValidated",
        "ReadyForApproval",
        "SubmissionAuthorized",
        "Submitting",
        "SubmissionUncertain",
    }
)

# From → allowed next statuses (plus same-status no-op).
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "New": frozenset(
        {
            "Eligible",
            "Needs review",
            "Skipped",
            "Closed",
            "Duplicate",
            "On hold",
        }
    ),
    "Needs review": frozenset(
        {
            "Eligible",
            "Skipped",
            "Closed",
            "Duplicate",
            "On hold",
            "In preparation",
            "Needs review",
        }
    ),
    "Eligible": frozenset(
        {
            "In preparation",
            "Preparing",
            "Ready for approval",
            "ReadyForApproval",
            "On hold",
            "Skipped",
            "Needs review",
            "Closed",
            "Duplicate",
        }
    ),
    "In preparation": frozenset(
        {
            "Ready for approval",
            "ReadyForApproval",
            "MaterialsValidated",
            "Needs review",
            "On hold",
            "Skipped",
            "Eligible",
            "Preparing",
        }
    ),
    "Preparing": frozenset(
        {
            "MaterialsValidated",
            "ReadyForApproval",
            "Ready for approval",
            "Needs review",
            "On hold",
            "Skipped",
            "In preparation",
        }
    ),
    "MaterialsValidated": frozenset(
        {
            "ReadyForApproval",
            "Ready for approval",
            "SubmissionAuthorized",
            "Needs review",
            "On hold",
            "Preparing",
            "In preparation",
        }
    ),
    "Ready for approval": frozenset(
        {
            "Submitted",
            "SubmissionAuthorized",
            "Submitting",
            "Needs review",
            "On hold",
            "Skipped",
            "In preparation",
            "Preparing",
        }
    ),
    "ReadyForApproval": frozenset(
        {
            "Submitted",
            "SubmissionAuthorized",
            "Submitting",
            "Needs review",
            "On hold",
            "Skipped",
            "In preparation",
            "Preparing",
            "Ready for approval",
        }
    ),
    "SubmissionAuthorized": frozenset(
        {
            "Submitting",
            "Submitted",
            "On hold",
            "SubmissionUncertain",
            "Needs review",
            "Ready for approval",
            "ReadyForApproval",
        }
    ),
    "Submitting": frozenset(
        {
            "Applied",
            "Submitted",
            "SubmissionUncertain",
            "On hold",
            "Needs review",
        }
    ),
    "Submitted": frozenset(
        {"Applied", "On hold", "Needs review", "Rejected", "Closed", "SubmissionUncertain"}
    ),
    "Applied": frozenset({"Follow-up due", "Rejected", "Closed", "On hold"}),
    "SubmissionUncertain": frozenset(
        {
            # No auto-retry to Submitting/Applied — reconcile only (Phase 4 P01)
            "On hold",
            "Needs review",
            "Applied",  # only after receipt reconcile
            "Rejected",
            "Closed",
        }
    ),
    "On hold": frozenset(
        {
            "Needs review",
            "Eligible",
            "Skipped",
            "Closed",
            "Ready for approval",
            "ReadyForApproval",
            "Submitted",
            "Applied",
            "SubmissionUncertain",
        }
    ),
    "Skipped": frozenset({"Needs review", "Closed", "Duplicate"}),
    "Closed": frozenset(),
    "Rejected": frozenset({"Closed"}),
    "Duplicate": frozenset(),
    "Follow-up due": frozenset({"Applied", "Closed", "Rejected", "On hold"}),
}

TOOL_PERMISSIONS: dict[str, frozenset[str]] = {
    "discovery": frozenset(
        {
            "http_fetch",
            "read_exclusion",
            "write_shard",
        }
    ),
    "frontier_rank": frozenset(
        {
            "http_fetch",
            "read_handoff",
            "write_expand_shard",
            "write_report",
        }
    ),
    "frontier_submit": frozenset(
        {
            "http_fetch",
            "read_handoff",
            "write_report",
            "browser",  # only with lock + authorize (Phase 3)
            "submit",
        }
    ),
    "harness": frozenset(
        {
            "ledger",
            "merge",
            "validate",
            "build_exclusion",
            "run_context",
        }
    ),
}

FORBIDDEN_FOR_DISCOVERY = frozenset({"browser", "submit", "write_handoff", "write_report"})


@dataclass
class PolicyVerdict:
    ok: bool
    code: str
    message: str
    blocking_reasons: list[str] = field(default_factory=list)
    decision: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
            "blocking_reasons": self.blocking_reasons,
            "decision": self.decision,
            "policy_version": POLICY_VERSION,
        }


def check_verified_fact_claim(text: str) -> PolicyVerdict:
    lowered = (text or "").lower()
    hits = [d for d in VERIFIED_FACT_DENYLIST if d in lowered]
    if hits:
        return PolicyVerdict(
            False,
            "verified_fact_denylist",
            f"invented or disallowed claim: {hits[0]}",
            blocking_reasons=hits,
        )
    return PolicyVerdict(True, "verified_fact_ok", "no denylist hits")


def tool_allowed(role: str, tool: str) -> PolicyVerdict:
    allowed = TOOL_PERMISSIONS.get(role)
    if allowed is None:
        return PolicyVerdict(False, "unknown_role", f"unknown role: {role}")
    if role == "discovery" and tool in FORBIDDEN_FOR_DISCOVERY:
        return PolicyVerdict(
            False,
            "discovery_forbidden_tool",
            f"discovery cannot use {tool}",
            blocking_reasons=[f"tool:{tool}"],
        )
    if tool not in allowed:
        return PolicyVerdict(
            False,
            "tool_not_permitted",
            f"role {role} cannot use {tool}",
            blocking_reasons=[f"tool:{tool}"],
        )
    if role == "frontier_submit" and tool in {"browser", "submit"}:
        # Caller must also hold a form lock; Phase 1 only encodes the role gate.
        return PolicyVerdict(
            True,
            "submit_role_ok",
            "frontier_submit may use browser/submit only with lock + daily cap",
        )
    return PolicyVerdict(True, "tool_ok", f"{role} may use {tool}")


def daily_submit_remaining(submits_today: int, cap: int = DAILY_SUBMIT_CAP) -> int:
    return max(0, cap - max(0, submits_today))


def check_daily_submit_cap(submits_today: int, cap: int = DAILY_SUBMIT_CAP) -> PolicyVerdict:
    remaining = daily_submit_remaining(submits_today, cap=cap)
    if remaining <= 0:
        return PolicyVerdict(
            False,
            "daily_submit_cap",
            f"daily submit cap reached ({cap})",
            blocking_reasons=["daily_submit_cap"],
        )
    return PolicyVerdict(True, "submit_cap_ok", f"remaining={remaining}")


def check_handoff_floor(cumulative: int, floor: int = HANDOFF_FLOOR_DEFAULT) -> PolicyVerdict:
    if cumulative >= floor:
        return PolicyVerdict(True, "floor_met", f"cumulative={cumulative} floor={floor}")
    return PolicyVerdict(
        False,
        "floor_unmet",
        f"cumulative={cumulative} < floor={floor}",
        blocking_reasons=["floor_unmet"],
    )


def can_transition(from_status: str, to_status: str) -> PolicyVerdict:
    if to_status not in ALLOWED_STATUSES:
        return PolicyVerdict(
            False,
            "unknown_status",
            f"status not in SOP §15: {to_status}",
            blocking_reasons=[f"status:{to_status}"],
        )
    if from_status == to_status:
        return PolicyVerdict(True, "noop", "same status")
    if from_status not in ALLOWED_STATUSES:
        return PolicyVerdict(
            False,
            "unknown_from_status",
            f"from status not in SOP §15: {from_status}",
            blocking_reasons=[f"status:{from_status}"],
        )
    allowed = STATUS_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        return PolicyVerdict(
            False,
            "illegal_transition",
            f"cannot transition {from_status} → {to_status}",
            blocking_reasons=[f"{from_status}->{to_status}"],
        )
    return PolicyVerdict(True, "transition_ok", f"{from_status} → {to_status}")


def text_blob(*parts: Any) -> str:
    return " ".join(str(p) for p in parts if p)


def is_hard_miss(text: str) -> Optional[str]:
    for pat in HARD_MISS_PATTERNS:
        m = pat.search(text or "")
        if m:
            return m.group(0)
    return None


def eligibility_safety_check(
    *,
    country: str,
    status: str,
    reason: str = "",
    posting_text: str = "",
    sponsorship_quote: str = "",
) -> PolicyVerdict:
    """
    E05-oriented gate: never mark Eligible on hard-miss fixtures.

    Hard misses: DE C1 / required German, visa not available, relocation≠sponsorship.
    """
    blob = text_blob(reason, posting_text, sponsorship_quote, country, status)
    miss = is_hard_miss(blob)
    proposed = (status or "").strip()

    if miss:
        if proposed.lower() == "eligible":
            return PolicyVerdict(
                False,
                "hard_miss_eligible_forbidden",
                f"must not mark Eligible: {miss}",
                blocking_reasons=[f"hard_miss:{miss}"],
                decision="Skipped",
            )
        return PolicyVerdict(
            True,
            "hard_miss_held",
            f"hard miss recognized: {miss}",
            blocking_reasons=[f"hard_miss:{miss}"],
            decision="Skipped" if proposed.lower() != "needs review" else proposed,
        )

    # Relocation language alone is not sponsorship for DE/IE/UAE.
    country_norm = (country or "").strip()
    needs_sponsor = country_norm in SPONSORSHIP_REQUIRED or country_norm.upper() in {
        "DE",
        "IE",
        "AE",
        "GERMANY",
        "IRELAND",
        "UAE",
    }
    if needs_sponsor and proposed.lower() == "eligible":
        sponsor_ok = bool(SPONSORSHIP_EVIDENCE.search(sponsorship_quote or posting_text or ""))
        reloc_only = bool(RELOCATION_NOT_SPONSORSHIP.search(blob)) and not sponsor_ok
        if reloc_only or not sponsor_ok:
            return PolicyVerdict(
                False,
                "sponsorship_not_evidenced",
                "relocation or missing sponsorship cannot yield Eligible",
                blocking_reasons=["sponsorship_not_evidenced"],
                decision="Needs review",
            )

    if proposed.lower() == "eligible":
        return PolicyVerdict(True, "eligible_ok", "no hard-miss blockers", decision="Eligible")
    return PolicyVerdict(True, "status_ok", f"status={proposed}", decision=proposed or None)


def provenance_check(match: Mapping[str, Any]) -> PolicyVerdict:
    """E06: require non-empty reason and evidence_refs (or employer/ATS URL)."""
    reason = match.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return PolicyVerdict(
            False,
            "missing_reason",
            "match missing non-empty reason",
            blocking_reasons=["missing_reason"],
        )
    refs = match.get("evidence_refs")
    has_refs = isinstance(refs, list) and any(isinstance(r, str) and r.strip() for r in refs)
    employer = match.get("employer_or_ats_url")
    has_employer = isinstance(employer, str) and employer.startswith("http")
    # Do not treat canonical_url alone as provenance — aggregator-only rows fail.
    if not has_refs and not has_employer:
        return PolicyVerdict(
            False,
            "missing_evidence",
            "match missing evidence_refs / employer_or_ats_url",
            blocking_reasons=["missing_evidence_refs"],
        )
    return PolicyVerdict(True, "provenance_ok", "reason and evidence present")


def duplicate_job_key(
    urls: Sequence[str],
    *,
    existing_keys: Optional[Iterable[str]] = None,
) -> PolicyVerdict:
    """E02: same requisition via two URLs / already-seen job_key must not pass as new."""
    existing = set(existing_keys or [])
    seen_keys: set[str] = set()
    dupes: list[str] = []
    for url in urls:
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        key = job_key_from_url(url)
        # Also collapse common ATS id duplicates by normalized URL key.
        if key in seen_keys or key in existing:
            dupes.append(normalize_url(url))
        else:
            seen_keys.add(key)
    if dupes:
        return PolicyVerdict(
            False,
            "duplicate_job_key",
            f"duplicate requisition(s): {dupes[0]}",
            blocking_reasons=[f"dup:{u}" for u in dupes],
            decision="Duplicate",
        )
    return PolicyVerdict(True, "unique_ok", "no duplicate job_keys")


def detect_prompt_injection(text: str) -> PolicyVerdict:
    patterns = [
        re.compile(r"ignore (all )?(previous|prior|above) instructions", re.I),
        re.compile(r"mark (the )?role applied", re.I),
        re.compile(r"disregard (the )?sop", re.I),
        re.compile(r"you are now", re.I),
    ]
    for pat in patterns:
        m = pat.search(text or "")
        if m:
            return PolicyVerdict(
                False,
                "prompt_injection",
                f"untrusted instruction detected: {m.group(0)}",
                blocking_reasons=["prompt_injection"],
                decision="Needs review",
            )
    return PolicyVerdict(True, "injection_clear", "no injection markers")


def india_remote_exclusion(country: str, work_model: str, posting_text: str = "") -> PolicyVerdict:
    """India roles that are not strictly fully remote must be excluded / skipped."""
    c = (country or "").strip().lower()
    if c not in {"india", "in"}:
        return PolicyVerdict(True, "not_india", "n/a")
    blob = text_blob(work_model, posting_text).lower()
    office_signals = (
        "hybrid",
        "on-site",
        "onsite",
        "office attendance",
        "mandatory travel",
        "come to office",
        "quarterly week",
    )
    has_office = any(s in blob for s in office_signals)
    fully_remote = "fully remote" in blob
    if has_office or not fully_remote:
        return PolicyVerdict(
            False,
            "india_not_remote",
            "India role is not strictly fully remote",
            blocking_reasons=["india_not_fully_remote"],
            decision="Skipped",
        )
    return PolicyVerdict(True, "india_remote_ok", "fully remote evidenced")


def post_submit_timeout_hold(*, confirmation_seen: bool, gmail_receipt: bool) -> PolicyVerdict:
    """Adversarial: timeout / uncertain submit must not become Applied."""
    if confirmation_seen and gmail_receipt:
        return PolicyVerdict(True, "applied_ok", "receipt present", decision="Applied")
    if confirmation_seen and not gmail_receipt:
        return PolicyVerdict(
            True,
            "submitted_pending_receipt",
            "portal confirmation without Gmail receipt → Submitted (not Applied)",
            decision="Submitted",
        )
    return PolicyVerdict(
        False,
        "submit_uncertain",
        "post-submit timeout / no confirmation → On hold",
        blocking_reasons=["submit_uncertain"],
        decision="On hold",
    )


def evaluate_match_for_eligibility(match: Mapping[str, Any]) -> PolicyVerdict:
    """Composite Phase-1 safety evaluation used by evals."""
    inj = detect_prompt_injection(text_blob(match.get("reason"), match.get("posting_text"), match.get("jd")))
    if not inj.ok:
        return inj

    india = india_remote_exclusion(
        str(match.get("country") or ""),
        str(match.get("work_model") or ""),
        str(match.get("posting_text") or match.get("jd") or ""),
    )
    if not india.ok:
        return india

    prov = provenance_check(match)
    if not prov.ok:
        return prov

    return eligibility_safety_check(
        country=str(match.get("country") or ""),
        status=str(match.get("status") or ""),
        reason=str(match.get("reason") or ""),
        posting_text=str(match.get("posting_text") or match.get("jd") or ""),
        sponsorship_quote=str(match.get("sponsorship_quote") or ""),
    )


def _cli() -> int:
    ap = argparse.ArgumentParser(description="JobOps policy checks")
    ap.add_argument("--check-match", help="JSON file with a match object")
    ap.add_argument("--tool-role")
    ap.add_argument("--tool-name")
    args = ap.parse_args()
    if args.tool_role and args.tool_name:
        print(json.dumps(tool_allowed(args.tool_role, args.tool_name).to_dict(), indent=2))
        return 0
    if args.check_match:
        data = json.loads(Path(args.check_match).read_text(encoding="utf-8"))
        print(json.dumps(evaluate_match_for_eligibility(data).to_dict(), indent=2))
        return 0
    print(json.dumps({"policy_version": POLICY_VERSION, "daily_submit_cap": DAILY_SUBMIT_CAP}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
