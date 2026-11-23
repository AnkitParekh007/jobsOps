#!/usr/bin/env python3
"""F03 Verification: V01 availability, V02/V03 rules, V04 duplicates → EligibilityDecision."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import (  # noqa: E402
    POLICY_VERSION,
    ContractError,
    attach_eligible_count,
    job_key_from_url,
    make_eligibility_decision,
    make_envelope,
    normalize_url,
    validate,
)
from ledger import Ledger  # noqa: E402
from policy import (  # noqa: E402
    RELOCATION_NOT_SPONSORSHIP,
    SPONSORSHIP_EVIDENCE,
    SPONSORSHIP_REQUIRED,
    is_hard_miss,
    text_blob,
)

PRODUCER = "verify_jobs"
ARTIFACT_TYPE = "eligibility_decision"

# Closed / gone signals in HTTP body or status.
CLOSED_STATUS_CODES = frozenset({404, 410})
CLOSED_BODY_PATTERNS = [
    re.compile(r"\b(job (has been )?closed|no longer (accepting|available)|position (has been )?filled)\b", re.I),
    re.compile(r"\b(this (job|role|posting) (is )?(no longer|not) available)\b", re.I),
    re.compile(r"\b(404|page not found|requisition not found)\b", re.I),
]

FetchFn = Callable[[str], tuple[int, str]]


@dataclass
class AvailabilityResult:
    state: str  # open | closed | unknown
    http_status: Optional[int] = None
    body: str = ""
    note: str = ""


@dataclass
class VerifyResult:
    decision: dict[str, Any]
    match_status: str
    availability: str
    used_agent: bool = False
    blocking_reasons: list[str] = field(default_factory=list)


def http_fetch(url: str, *, timeout: float = 12.0) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "JobOps-verify/1.0 (+local research)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(400_000)
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                text = raw.decode(charset, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            return int(resp.status), text
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(50_000).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        return int(exc.code), body
    except Exception as exc:  # noqa: BLE001
        return 0, f"fetch_error:{type(exc).__name__}:{exc}"


def check_availability(
    url: str,
    *,
    fetch: Optional[FetchFn] = None,
    prefetched_status: Optional[int] = None,
    prefetched_body: Optional[str] = None,
) -> AvailabilityResult:
    """V01 — open / closed / unknown."""
    if prefetched_status is not None or prefetched_body is not None:
        status = int(prefetched_status or 0)
        body = prefetched_body or ""
    else:
        fetcher = fetch or http_fetch
        try:
            status, body = fetcher(url)
        except Exception as exc:  # noqa: BLE001
            return AvailabilityResult("unknown", None, "", f"fetch_failed:{exc}")

    if status in CLOSED_STATUS_CODES:
        return AvailabilityResult("closed", status, body, f"http_{status}")
    if status == 0:
        return AvailabilityResult("unknown", 0, body, "network_or_dns_failure")
    if status >= 500:
        return AvailabilityResult("unknown", status, body, f"http_{status}")
    if 200 <= status < 400:
        for pat in CLOSED_BODY_PATTERNS:
            m = pat.search(body or "")
            if m:
                return AvailabilityResult("closed", status, body, f"body:{m.group(0)}")
        return AvailabilityResult("open", status, body, "ok")
    # 401/403/429 etc. — cannot prove open or closed
    return AvailabilityResult("unknown", status, body, f"http_{status}")


def load_exclusion_urls(path: Optional[Path]) -> set[str]:
    if not path or not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for u in data.get("canonical_urls") or []:
        if isinstance(u, str) and u.startswith("http"):
            out.add(normalize_url(u))
    return out


def is_duplicate(
    url: str,
    *,
    exclusion: set[str],
    prior_keys: set[str],
    seen_in_batch: set[str],
) -> Optional[str]:
    """V04 — exclusion index, ledger prior job_key, or within-batch dup."""
    canon = normalize_url(url)
    key = job_key_from_url(canon)
    if canon in exclusion:
        return "exclusion_index"
    if key in prior_keys:
        return "ledger_prior_job_key"
    if key in seen_in_batch:
        return "batch_duplicate"
    return None


def country_needs_sponsorship(country: str) -> bool:
    c = (country or "").strip()
    if c in SPONSORSHIP_REQUIRED:
        return True
    return c.upper() in {"DE", "IE", "AE", "GERMANY", "IRELAND", "UAE"}


def apply_requirement_rules(
    *,
    country: str,
    posting_text: str,
    reason: str = "",
    evidence_quote: str = "",
    sponsorship_quote: str = "",
) -> tuple[str, list[str], Optional[str], bool, bool]:
    """
    V02/V03 — hard-miss → Skipped; sponsorship gate.

    Returns: (decision, blocking_reasons, sponsorship_evidence, hard_miss, ambiguous)
    ambiguous=True means thin agent may extract a sponsorship quote.
    """
    blob = text_blob(posting_text, reason, evidence_quote, sponsorship_quote)
    miss = is_hard_miss(blob)
    if miss:
        return (
            "Skipped",
            [f"hard_miss:{miss}"],
            None,
            True,
            False,
        )

    needs = country_needs_sponsorship(country)
    sponsor_src = sponsorship_quote or evidence_quote or posting_text
    sponsor_match = SPONSORSHIP_EVIDENCE.search(sponsor_src or "")
    reloc_only = bool(RELOCATION_NOT_SPONSORSHIP.search(blob)) and not sponsor_match

    if not needs:
        # Non-sponsorship countries: no hard miss → Eligible if open (caller sets).
        return ("Eligible", [], None, False, False)

    if sponsor_match:
        quote = sponsor_match.group(0)
        # Prefer a longer nearby snippet if available.
        if sponsorship_quote and SPONSORSHIP_EVIDENCE.search(sponsorship_quote):
            quote = sponsorship_quote.strip()
        elif evidence_quote and SPONSORSHIP_EVIDENCE.search(evidence_quote):
            quote = evidence_quote.strip()
        return ("Eligible", [], quote, False, False)

    if reloc_only:
        return (
            "Needs review",
            ["sponsorship_not_evidenced", "relocation_not_sponsorship"],
            None,
            False,
            False,
        )

    # Missing explicit sponsorship — never Eligible by inference.
    # Ambiguous if body has weak visa/work-auth language without clear sponsor phrase.
    weak = re.search(
        r"\b(visa|work (permit|authorization|authorisation)|immigration|right to work)\b",
        blob,
        re.I,
    )
    ambiguous = bool(weak)
    reasons = ["sponsorship_not_evidenced"]
    if ambiguous:
        reasons.append("sponsorship_ambiguous")
    return ("Needs review", reasons, None, False, ambiguous)


def parse_agent_eligibility_output(raw: str | Mapping[str, Any]) -> dict[str, Any]:
    """
    Harness gate: agent output must be EligibilityDecision JSON (object or envelope).
    Free-text / markdown prose is rejected.
    """
    if isinstance(raw, Mapping):
        data: Any = dict(raw)
    else:
        text = (raw or "").strip()
        if not text:
            raise ContractError("verification agent output is empty")
        # Reject obvious free-text (no JSON object).
        if not text.startswith("{") and not text.startswith("["):
            raise ContractError("verification agent output must be JSON EligibilityDecision, not free text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ContractError(f"verification agent output is not valid JSON: {exc}") from exc

    # Allow envelope wrapping: {payload: EligibilityDecision} or bare decision.
    if isinstance(data, dict) and "payload" in data and "decision" not in data:
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise ContractError("envelope payload must be an EligibilityDecision object")
        data = payload

    if not isinstance(data, dict):
        raise ContractError("EligibilityDecision must be a JSON object")

    # Must have structured decision enum — reject prose-only objects.
    decision = data.get("decision")
    if not isinstance(decision, str) or decision not in {
        "Eligible",
        "Needs review",
        "Skipped",
        "Closed",
        "Duplicate",
    }:
        raise ContractError("EligibilityDecision.decision missing or invalid")

    validate(data, "eligibility-decision.schema.json")
    return dict(data)


def verify_match(
    match: Mapping[str, Any],
    *,
    exclusion: Optional[set[str]] = None,
    prior_keys: Optional[set[str]] = None,
    seen_in_batch: Optional[set[str]] = None,
    fetch: Optional[FetchFn] = None,
    offline: bool = False,
    agent_decisions: Optional[Mapping[str, Mapping[str, Any]]] = None,
    policy_version: str = POLICY_VERSION,
) -> VerifyResult:
    """Run V01→V04 for one handoff match. Never invent Eligible without evidence."""
    exclusion = exclusion or set()
    prior_keys = prior_keys or set()
    seen = seen_in_batch if seen_in_batch is not None else set()

    url = match.get("canonical_url") or match.get("employer_or_ats_url") or ""
    if not isinstance(url, str) or not url.startswith("http"):
        decision = make_eligibility_decision(
            job_key="url:invalid",
            canonical_url="https://invalid.local/missing",
            decision="Skipped",
            blocking_reasons=["missing_canonical_url"],
            evidence_refs=[],
            hard_miss=False,
            policy_version=policy_version,
            notes="invalid match url",
        )
        return VerifyResult(decision, "Skipped", "unknown", blocking_reasons=["missing_canonical_url"])

    canon = normalize_url(url)
    employer = normalize_url(str(match.get("employer_or_ats_url") or canon))
    jk = str(match.get("job_key") or job_key_from_url(canon))
    refs = [employer]

    # --- V04 Duplicate ---
    dup_reason = is_duplicate(
        canon,
        exclusion=exclusion,
        prior_keys=prior_keys,
        seen_in_batch=seen,
    )
    if dup_reason:
        decision = make_eligibility_decision(
            job_key=jk,
            canonical_url=canon,
            decision="Duplicate",
            blocking_reasons=[f"duplicate:{dup_reason}"],
            evidence_refs=refs,
            hard_miss=False,
            policy_version=policy_version,
            notes=dup_reason,
        )
        return VerifyResult(decision, "Duplicate", "unknown", blocking_reasons=decision["blocking_reasons"])

    seen.add(jk)

    # --- V01 Availability ---
    posting_text = str(match.get("posting_text") or match.get("jd") or "")
    avail_override = match.get("availability")
    if offline or avail_override in {"open", "closed", "unknown"}:
        state = str(avail_override or "open")
        body = posting_text
        avail = AvailabilityResult(state, None, body, "fixture_or_offline")
    else:
        avail = check_availability(
            employer,
            fetch=fetch,
            prefetched_status=match.get("http_status") if isinstance(match.get("http_status"), int) else None,
            prefetched_body=posting_text or None,
        )
        if not posting_text and avail.body:
            posting_text = avail.body

    if avail.state == "closed":
        decision = make_eligibility_decision(
            job_key=jk,
            canonical_url=canon,
            decision="Closed",
            blocking_reasons=[f"availability:closed:{avail.note}"],
            evidence_refs=refs,
            hard_miss=False,
            policy_version=policy_version,
            notes=avail.note,
        )
        return VerifyResult(decision, "Closed", "closed", blocking_reasons=decision["blocking_reasons"])

    if avail.state == "unknown":
        # Unknown availability → Needs review (never Eligible).
        decision = make_eligibility_decision(
            job_key=jk,
            canonical_url=canon,
            decision="Needs review",
            blocking_reasons=[f"availability:unknown:{avail.note or 'unconfirmed'}"],
            evidence_refs=refs,
            hard_miss=False,
            policy_version=policy_version,
            notes="availability unknown",
        )
        return VerifyResult(
            decision,
            "Needs review",
            "unknown",
            blocking_reasons=decision["blocking_reasons"],
        )

    # --- V02 / V03 Rules ---
    reason = str(match.get("reason") or "")
    evidence_quote = str(match.get("evidence_quote") or "")
    sponsorship_quote = str(match.get("sponsorship_quote") or match.get("sponsorship_evidence") or "")
    country = str(match.get("country") or "")

    status, blocking, sponsor_ev, hard_miss, ambiguous = apply_requirement_rules(
        country=country,
        posting_text=posting_text,
        reason=reason,
        evidence_quote=evidence_quote,
        sponsorship_quote=sponsorship_quote,
    )

    used_agent = False
    if ambiguous and agent_decisions:
        agent_raw = agent_decisions.get(jk) or agent_decisions.get(canon)
        if agent_raw is not None:
            agent_dec = parse_agent_eligibility_output(agent_raw)
            # Agent may only refine sponsorship; never override hard_miss/closed/dup.
            used_agent = True
            status = agent_dec["decision"]
            blocking = list(agent_dec.get("blocking_reasons") or [])
            sponsor_ev = agent_dec.get("sponsorship_evidence")
            hard_miss = bool(agent_dec.get("hard_miss"))
            if agent_dec.get("evidence_refs"):
                refs = [str(r) for r in agent_dec["evidence_refs"]]

    # Final safety: never Eligible without explicit sponsorship for sponsor countries.
    if status == "Eligible" and country_needs_sponsorship(country):
        if not sponsor_ev or not SPONSORSHIP_EVIDENCE.search(str(sponsor_ev)):
            # Check posting one more time
            if not SPONSORSHIP_EVIDENCE.search(posting_text or ""):
                status = "Needs review"
                blocking = list(blocking) + ["sponsorship_not_evidenced"]
                sponsor_ev = None
                hard_miss = False

    if status == "Eligible" and hard_miss:
        status = "Skipped"
        blocking = list(blocking) or ["hard_miss"]

    decision = make_eligibility_decision(
        job_key=jk,
        canonical_url=canon,
        decision=status,
        blocking_reasons=blocking,
        evidence_refs=refs,
        sponsorship_evidence=sponsor_ev,
        hard_miss=hard_miss,
        policy_version=policy_version,
        notes="agent" if used_agent else "",
    )
    return VerifyResult(
        decision,
        status,
        avail.state,
        used_agent=used_agent,
        blocking_reasons=list(decision["blocking_reasons"]),
    )


def enrich_handoff_match(match: MutableMapping[str, Any], result: VerifyResult) -> None:
    """Write verification fields onto a handoff-state match (compat-preserving)."""
    d = result.decision
    match["status"] = result.match_status
    match["job_key"] = d["job_key"]
    match["eligibility_decision"] = d["decision"]
    match["blocking_reasons"] = list(d.get("blocking_reasons") or [])
    match["verification"] = {
        "availability": result.availability,
        "hard_miss": bool(d.get("hard_miss")),
        "sponsorship_evidence": d.get("sponsorship_evidence"),
        "policy_version": d.get("policy_version"),
        "used_agent": result.used_agent,
    }
    if d.get("sponsorship_evidence"):
        match["sponsorship_quote"] = d["sponsorship_evidence"]
    # Keep / set reason if empty.
    if not str(match.get("reason") or "").strip():
        br = d.get("blocking_reasons") or []
        match["reason"] = "; ".join(br) if br else f"verified:{d['decision']}"


def verify_handoff_state(
    state: MutableMapping[str, Any],
    *,
    run_id: str,
    exclusion: Optional[set[str]] = None,
    prior_keys: Optional[set[str]] = None,
    fetch: Optional[FetchFn] = None,
    offline: bool = False,
    agent_decisions: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ledger: Optional[Ledger] = None,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    """Verify all matches; enrich state; optionally write ledger artifacts."""
    matches = state.get("matches")
    if not isinstance(matches, list):
        matches = []
        state["matches"] = matches

    exclusion = exclusion or set()
    # Prior keys for V04: ledger jobs that existed *before* this run's discovery ingest.
    # Callers pass keys from a snapshot; default empty means only exclusion + batch dup.
    prior = set(prior_keys or [])
    seen: set[str] = set()
    decisions: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    counts = {
        "Eligible": 0,
        "Needs review": 0,
        "Skipped": 0,
        "Closed": 0,
        "Duplicate": 0,
    }

    for raw in matches:
        if not isinstance(raw, dict):
            continue
        result = verify_match(
            raw,
            exclusion=exclusion,
            prior_keys=prior,
            seen_in_batch=seen,
            fetch=fetch,
            offline=offline,
            agent_decisions=agent_decisions,
            policy_version=policy_version,
        )
        enrich_handoff_match(raw, result)
        decisions.append(result.decision)
        counts[result.decision["decision"]] = counts.get(result.decision["decision"], 0) + 1

        if "sponsorship_ambiguous" in (result.blocking_reasons or []) and not result.used_agent:
            ambiguous.append(
                {
                    "job_key": result.decision["job_key"],
                    "canonical_url": result.decision["canonical_url"],
                    "country": raw.get("country"),
                    "organization": raw.get("organization"),
                    "role": raw.get("role"),
                }
            )

        if ledger is not None:
            env = make_envelope(
                run_id=run_id,
                producer=PRODUCER,
                artifact_type=ARTIFACT_TYPE,
                payload=result.decision,
                job_key=result.decision["job_key"],
                task_id=f"{run_id}:verify",
                evidence_refs=result.decision.get("evidence_refs") or [],
                blocking_reasons=result.decision.get("blocking_reasons") or [],
                status=result.decision["decision"],
            )
            ledger.append_artifact(env)
            ledger.transition_job(
                result.decision["job_key"],
                canonical_url=result.decision["canonical_url"],
                status=result.match_status,
                run_id=run_id,
                organization=str(raw.get("organization") or ""),
                role=str(raw.get("role") or ""),
                country=str(raw.get("country") or ""),
                lane=raw.get("lane"),
                meta={
                    "verification": result.availability,
                    "hard_miss": result.decision.get("hard_miss"),
                },
            )

    attach_eligible_count(state)
    state["verification"] = {
        "run_id": run_id,
        "counts": counts,
        "decision_count": len(decisions),
        "ambiguous_count": len(ambiguous),
        "policy_version": policy_version,
    }
    # Ensure phase stays valid for handoff-state schema.
    if state.get("phase") not in {"discovery", "post-discovery", "complete"}:
        state["phase"] = "post-discovery"

    return {
        "ok": True,
        "run_id": run_id,
        "counts": counts,
        "eligible_count": state.get("eligible_count", 0),
        "decision_count": len(decisions),
        "ambiguous": ambiguous,
        "decisions": decisions,
    }


def load_agent_decisions_file(path: Optional[Path]) -> dict[str, dict[str, Any]]:
    """Load optional agent outputs: list of EligibilityDecision or {job_key: decision}."""
    if not path or not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")
    # Reject free-text files early.
    stripped = raw.strip()
    if not stripped.startswith("{") and not stripped.startswith("["):
        raise ContractError("agent decisions file must be JSON, not free text")
    data = json.loads(stripped)
    out: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict) and "decisions" in data:
        data = data["decisions"]
    if isinstance(data, list):
        for item in data:
            dec = parse_agent_eligibility_output(item)
            out[dec["job_key"]] = dec
            out[normalize_url(dec["canonical_url"])] = dec
    elif isinstance(data, dict):
        # Either a single decision or a map.
        if "decision" in data and "job_key" in data:
            dec = parse_agent_eligibility_output(data)
            out[dec["job_key"]] = dec
            out[normalize_url(dec["canonical_url"])] = dec
        else:
            for k, v in data.items():
                dec = parse_agent_eligibility_output(v)
                out[str(k)] = dec
                out[dec["job_key"]] = dec
                out[normalize_url(dec["canonical_url"])] = dec
    else:
        raise ContractError("agent decisions file must be object or array")
    return out


def _cli() -> int:
    ap = argparse.ArgumentParser(description="JobOps F03 verify_jobs (V01–V04)")
    ap.add_argument("--state", required=True, help="handoff-state.json path")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--exclusion", default="", help="exclusion-index.json")
    ap.add_argument("--db", default="", help="SQLite ledger path (optional)")
    ap.add_argument("--out", default="", help="write decisions summary JSON")
    ap.add_argument("--ambiguous-out", default="", help="write ambiguous sponsorship queue")
    ap.add_argument("--agent-decisions", default="", help="JSON EligibilityDecision(s) from thin agent")
    ap.add_argument("--offline", action="store_true", help="skip HTTP; use fixture availability/posting_text")
    ap.add_argument(
        "--prior-keys-mode",
        choices=["none", "ledger"],
        default="none",
        help="V04 prior keys: none (exclusion+batch only) or ledger (all jobs — use carefully)",
    )
    args = ap.parse_args()

    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    exclusion = load_exclusion_urls(Path(args.exclusion) if args.exclusion else None)

    ledger: Optional[Ledger] = None
    prior_keys: set[str] = set()
    if args.db:
        ledger = Ledger(args.db)
        if args.prior_keys_mode == "ledger":
            # Prior = jobs first seen on an earlier run (not this run).
            # Excludes same-run re-verify so Skipped/Closed from pass-1 are not
            # reclassified Duplicate when the optional agent pass re-runs verify.
            rows = ledger._conn.execute(  # noqa: SLF001
                "SELECT job_key, first_seen_run_id, status FROM jobs"
            ).fetchall()
            prior_keys = {
                r["job_key"]
                for r in rows
                if r["first_seen_run_id"] and r["first_seen_run_id"] != args.run_id
            }

    try:
        agent_decisions = load_agent_decisions_file(
            Path(args.agent_decisions) if args.agent_decisions else None
        )
    except ContractError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        if ledger:
            ledger.close()
        return 2

    summary = verify_handoff_state(
        state,
        run_id=args.run_id,
        exclusion=exclusion,
        prior_keys=prior_keys,
        offline=args.offline,
        agent_decisions=agent_decisions or None,
        ledger=ledger,
    )

    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    if args.ambiguous_out:
        Path(args.ambiguous_out).write_text(
            json.dumps({"ambiguous": summary["ambiguous"]}, indent=2) + "\n",
            encoding="utf-8",
        )

    out_payload = {
        "ok": True,
        "run_id": args.run_id,
        "counts": summary["counts"],
        "eligible_count": summary["eligible_count"],
        "decision_count": summary["decision_count"],
        "ambiguous_count": len(summary["ambiguous"]),
        "state": str(state_path),
    }
    if args.out:
        # Full decisions for ledger/debug (may be large).
        Path(args.out).write_text(
            json.dumps({**out_payload, "decisions": summary["decisions"]}, indent=2) + "\n",
            encoding="utf-8",
        )

    if ledger:
        ledger.set_phase(args.run_id, "verified")
        ledger.mark_task(
            f"{args.run_id}:verify",
            args.run_id,
            "verify",
            "complete",
            finished=True,
            detail={"counts": summary["counts"], "eligible_count": summary["eligible_count"]},
        )
        ledger.close()

    print(json.dumps(out_payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
