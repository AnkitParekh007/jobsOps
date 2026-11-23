#!/usr/bin/env python3
"""F04 Intelligence: I01–I04 deterministic ranking → top-5 shortlist (no fictional % certainty)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Sequence

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import (  # noqa: E402
    POLICY_VERSION,
    attach_eligible_count,
    job_key_from_url,
    make_envelope,
    normalize_url,
    validate,
)
from ledger import Ledger  # noqa: E402
from policy import COUNTRY_PRIORITY, text_blob  # noqa: E402

PRODUCER = "rank_opportunities"
ARTIFACT_TYPE = "ranked_shortlist"
SHORTLIST_SIZE = 5

# Verified profile terms (from SOP §2 / F01 baseline) — never invent beyond these.
VERIFIED_SKILL_TERMS = (
    "angular",
    "react",
    "typescript",
    "javascript",
    "frontend",
    "front-end",
    "enterprise",
    "rag",
    "agentic",
    "workflow",
    "approvals",
    "audit",
    "sop",
    "copilot",
    "co-pilot",
)

SENIORITY_TERMS = (
    "senior",
    "staff",
    "principal",
    "lead",
    "architect",
    "forward deployed",
    "forward-deployed",
)

DOMAIN_TERMS = (
    "ai",
    "llm",
    "agent",
    "frontend architecture",
    "platform",
    "product engineer",
)

COUNTRY_RANK = {name.lower(): idx for idx, name in enumerate(COUNTRY_PRIORITY)}
COUNTRY_ALIASES = {
    "de": "germany",
    "ie": "ireland",
    "ae": "uae",
    "uae": "uae",
    "my": "malaysia",
    "sg": "singapore",
    "in": "india",
    "germany": "germany",
    "ireland": "ireland",
    "malaysia": "malaysia",
    "singapore": "singapore",
    "india": "india",
}


def _norm_country(country: str) -> str:
    c = (country or "").strip().lower()
    return COUNTRY_ALIASES.get(c, c)


def country_priority_score(country: str) -> float:
    """Higher is better. Unknown countries score below listed priority."""
    key = _norm_country(country)
    if key in COUNTRY_RANK:
        # Germany=1.0 … India lower
        n = len(COUNTRY_PRIORITY)
        return float(n - COUNTRY_RANK[key]) / float(n)
    return 0.1


def lane_priority_score(lane: Any) -> float:
    try:
        n = int(lane)
    except (TypeError, ValueError):
        return 0.25
    if n <= 0:
        return 0.25
    # Lane 1 highest
    return max(0.1, 1.0 - (n - 1) * 0.2)


def _tokenize(text: str) -> list[str]:
    return sorted(set(re.findall(r"[a-z0-9][a-z0-9+.#/-]*", (text or "").lower())))


def extract_requirement_terms(posting_text: str, *, max_terms: int = 40) -> list[str]:
    """Transparent keyword candidates from posting (not a fictional ATS certainty %)."""
    tokens = _tokenize(posting_text)
    stop = {
        "and",
        "the",
        "for",
        "with",
        "you",
        "our",
        "will",
        "are",
        "this",
        "that",
        "from",
        "have",
        "your",
        "job",
        "role",
        "team",
        "work",
        "experience",
        "years",
        "about",
        "ability",
        "strong",
        "good",
        "etc",
    }
    # Prefer known skill-ish tokens + longer tokens
    scored: list[tuple[int, str]] = []
    for t in tokens:
        if t in stop or len(t) < 3:
            continue
        boost = 2 if t in VERIFIED_SKILL_TERMS or t in DOMAIN_TERMS else 0
        boost += 1 if len(t) >= 6 else 0
        scored.append((boost, t))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out: list[str] = []
    seen: set[str] = set()
    for _, t in scored:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_terms:
            break
    return out


def score_profile_fit(
    *,
    posting_text: str,
    reason: str = "",
    sponsorship_evidence: Optional[str] = None,
    country: str = "",
    eligibility: str = "Eligible",
) -> tuple[float, list[str], dict[str, Any]]:
    """I01 — profile-fit from verified facts vs extracted requirements (0–100)."""
    blob = text_blob(posting_text, reason).lower()
    gaps: list[str] = []
    components: dict[str, float] = {}

    # Skills overlap with verified set (40)
    skill_hits = [t for t in VERIFIED_SKILL_TERMS if t in blob]
    skill_score = min(40.0, len(set(skill_hits)) * 5.0)
    if skill_score < 15:
        gaps.append("limited_verified_skill_overlap")
    components["skills"] = skill_score

    # Seniority / domain (25)
    sen = any(t in blob for t in SENIORITY_TERMS)
    dom = any(t in blob for t in DOMAIN_TERMS)
    seniority = (15.0 if sen else 5.0) + (10.0 if dom else 0.0)
    if not sen:
        gaps.append("seniority_not_evidenced_in_posting")
    components["seniority_domain"] = seniority

    # Location / sponsorship path (20)
    loc = 10.0
    if eligibility == "Eligible":
        loc = 20.0 if sponsorship_evidence or _norm_country(country) in {
            "malaysia",
            "singapore",
            "india",
        } else 15.0
    else:
        loc = 5.0
        gaps.append("eligibility_needs_review")
    components["location_auth"] = loc

    # Submission path exists signal (15) — Eligible implies open+path; Needs review lowers
    path = 15.0 if eligibility == "Eligible" else 5.0
    components["submission_path"] = path

    total = round(sum(components.values()), 1)
    total = max(0.0, min(100.0, total))
    return total, gaps, {"components": components, "skill_hits": sorted(set(skill_hits))}


def score_ats_keyword_coverage(
    posting_text: str,
    resume_or_verified_text: str = "",
) -> tuple[float, list[str], list[str], dict[str, Any]]:
    """
    I02 — transparent term overlap estimate (0–100).
    Not a claim of employer-scanner certainty — only verified-term overlap.
    """
    reqs = extract_requirement_terms(posting_text)
    if not reqs:
        return 0.0, [], [], {"note": "no_requirement_terms_extracted"}

    corpus = (resume_or_verified_text or " ".join(VERIFIED_SKILL_TERMS)).lower()
    matched: list[str] = []
    missing: list[str] = []
    for term in reqs:
        if term in corpus or any(term in v or v in term for v in VERIFIED_SKILL_TERMS):
            matched.append(term)
        else:
            missing.append(term)

    coverage = round(100.0 * len(matched) / max(1, len(reqs)), 1)
    return coverage, matched, missing, {"requirement_term_count": len(reqs)}


def parse_posting_date(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        # unix seconds
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    text = str(raw).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(text.replace("+00:00", "Z"), fmt.replace("%z", "Z") if text.endswith("Z") else fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    # ISO parse best-effort
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def score_interview_opportunity(
    *,
    posting_text: str,
    posting_date: Any = None,
    sponsorship_evidence: Optional[str] = None,
    country: str = "",
    eligibility: str = "Eligible",
    recruiter_reply: bool = False,
    referral_recorded: bool = False,
    compensation_disclosed: bool = False,
    now: Optional[datetime] = None,
) -> tuple[float, list[str], dict[str, Any]]:
    """I03 — SOP §13 interview-opportunity components; unknown = 0, no rescale."""
    now = now or datetime.now(timezone.utc)
    unknowns: list[str] = []
    parts: dict[str, float] = {}
    blob = (posting_text or "").lower()

    # Verified technical fit: 30
    tech_hits = sum(1 for t in VERIFIED_SKILL_TERMS if t in blob)
    if tech_hits >= 3:
        parts["technical_fit"] = 30.0
    elif tech_hits >= 1:
        parts["technical_fit"] = 15.0
    else:
        parts["technical_fit"] = 0.0
        unknowns.append("technical_fit")

    # Seniority and role fit: 20
    if any(t in blob for t in SENIORITY_TERMS):
        parts["seniority_role_fit"] = 20.0
    else:
        parts["seniority_role_fit"] = 0.0
        unknowns.append("seniority_role_fit")

    # Location / work auth incl sponsorship: 20
    if eligibility == "Eligible" and (
        sponsorship_evidence
        or _norm_country(country) in {"malaysia", "singapore", "india"}
    ):
        parts["location_auth"] = 20.0
    elif eligibility == "Eligible":
        parts["location_auth"] = 10.0
    else:
        parts["location_auth"] = 0.0
        unknowns.append("location_auth")

    # Freshness: 15 / 10 / 5 / 0
    dt = parse_posting_date(posting_date)
    if dt is None:
        parts["freshness"] = 0.0
        unknowns.append("posting_date")
    else:
        age_h = (now - dt).total_seconds() / 3600.0
        if age_h <= 72:
            parts["freshness"] = 15.0
        elif age_h <= 24 * 7:
            parts["freshness"] = 10.0
        elif age_h <= 24 * 30:
            parts["freshness"] = 5.0
        else:
            parts["freshness"] = 0.0

    # Recruiter / referral: 10 — 0 unless evidenced
    if recruiter_reply or referral_recorded:
        parts["recruiter_referral"] = 10.0
    else:
        parts["recruiter_referral"] = 0.0
        unknowns.append("recruiter_referral")

    # Compensation: 5 — 0 unless disclosed
    if compensation_disclosed:
        parts["compensation"] = 5.0
    else:
        parts["compensation"] = 0.0
        unknowns.append("compensation")

    total = round(sum(parts.values()), 1)
    return total, unknowns, {"components": parts, "unknowns": unknowns}


def score_priority(
    *,
    lane: Any,
    country: str,
    freshness_component: float,
    profile_fit: float,
    interview_opportunity: float,
) -> float:
    """I04 — lane × country × freshness composite (deterministic, transparent)."""
    lane_s = lane_priority_score(lane)
    country_s = country_priority_score(country)
    fresh_s = freshness_component / 15.0  # normalize 0–1 from I03 freshness max
    # Blend quality signals so shortlist prefers fit, not only geography
    quality = (profile_fit / 100.0) * 0.45 + (interview_opportunity / 100.0) * 0.25
    geo = lane_s * 0.15 + country_s * 0.10 + fresh_s * 0.05
    return round(quality + geo, 6)


def _match_eligibility(match: Mapping[str, Any]) -> Optional[str]:
    for key in ("eligibility_decision", "status"):
        val = match.get(key)
        if isinstance(val, str) and val.strip() in {"Eligible", "Needs review"}:
            return val.strip()
    return None


def rank_match(
    match: Mapping[str, Any],
    *,
    verified_resume_text: str = "",
    policy_version: str = POLICY_VERSION,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Rank one Eligible or Needs review match. Returns RankedOpportunity or None."""
    eligibility = _match_eligibility(match)
    if eligibility is None:
        return None

    url = match.get("canonical_url") or match.get("employer_or_ats_url") or ""
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    canon = normalize_url(url)
    jk = str(match.get("job_key") or job_key_from_url(canon))
    posting = str(
        match.get("posting_text")
        or match.get("jd")
        or match.get("evidence_quote")
        or match.get("reason")
        or ""
    )
    sponsor = match.get("sponsorship_quote") or match.get("sponsorship_evidence")
    if isinstance(sponsor, str):
        sponsor_ev: Optional[str] = sponsor
    else:
        sponsor_ev = None
        ver = match.get("verification")
        if isinstance(ver, dict) and ver.get("sponsorship_evidence"):
            sponsor_ev = str(ver["sponsorship_evidence"])

    country = str(match.get("country") or "")
    profile, gaps, profile_bd = score_profile_fit(
        posting_text=posting,
        reason=str(match.get("reason") or ""),
        sponsorship_evidence=sponsor_ev,
        country=country,
        eligibility=eligibility,
    )
    ats_cov, matched, missing, ats_bd = score_ats_keyword_coverage(
        posting, verified_resume_text or " ".join(VERIFIED_SKILL_TERMS)
    )
    interview, unknowns, interview_bd = score_interview_opportunity(
        posting_text=posting,
        posting_date=match.get("posting_date") or match.get("posted_at"),
        sponsorship_evidence=sponsor_ev,
        country=country,
        eligibility=eligibility,
        recruiter_reply=bool(match.get("recruiter_reply")),
        referral_recorded=bool(match.get("referral_recorded")),
        compensation_disclosed=bool(match.get("compensation_disclosed")),
        now=now,
    )
    freshness = float((interview_bd.get("components") or {}).get("freshness") or 0.0)
    priority = score_priority(
        lane=match.get("lane"),
        country=country,
        freshness_component=freshness,
        profile_fit=profile,
        interview_opportunity=interview,
    )

    gaps = list(gaps)
    for u in unknowns:
        gaps.append(f"unknown:{u}")
    if missing[:5]:
        gaps.append(f"missing_keywords:{','.join(missing[:5])}")

    refs = match.get("evidence_refs")
    if isinstance(refs, list) and refs:
        evidence_refs = [str(r) for r in refs]
    else:
        employer = match.get("employer_or_ats_url") or canon
        evidence_refs = [normalize_url(str(employer))]

    ranked = {
        "job_key": jk,
        "canonical_url": canon,
        "organization": str(match.get("organization") or ""),
        "role": str(match.get("role") or ""),
        "lane": match.get("lane"),
        "country": country,
        "eligibility_decision": eligibility,
        "queue": "human_review" if eligibility == "Needs review" else "ranked",
        "rank": 0,  # filled after sort
        "shortlist": False,
        "scores": {
            "profile_fit": profile,
            "ats_keyword_coverage": ats_cov,
            "interview_opportunity": interview,
            "priority": priority,
        },
        "score_breakdown": {
            "i01_profile_fit": profile_bd,
            "i02_ats_keyword_coverage": ats_bd,
            "i03_interview_opportunity": interview_bd,
            "i04_priority": {
                "lane_score": lane_priority_score(match.get("lane")),
                "country_score": country_priority_score(country),
                "freshness_component": freshness,
            },
            "certainty_note": "No fictional percent certainty — scores are transparent overlap / SOP §13 components only.",
        },
        "gaps": gaps,
        "evidence_refs": evidence_refs,
        "matched_terms": matched[:20],
        "missing_terms": missing[:20],
        "policy_version": policy_version,
        "notes": "",
    }
    # rank/shortlist filled after sort in rank_opportunities(); validate there.
    return ranked


def rank_opportunities(
    matches: Sequence[Mapping[str, Any]],
    *,
    include_needs_review: bool = True,
    shortlist_size: int = SHORTLIST_SIZE,
    verified_resume_text: str = "",
    policy_version: str = POLICY_VERSION,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Rank Eligible (and optionally Needs review) matches.
    Top `shortlist_size` Eligible go on shortlist; Needs review → human_review queue.
    """
    eligible_ranked: list[dict[str, Any]] = []
    review_ranked: list[dict[str, Any]] = []

    for m in matches:
        if not isinstance(m, Mapping):
            continue
        elig = _match_eligibility(m)
        if elig == "Eligible":
            r = rank_match(
                m,
                verified_resume_text=verified_resume_text,
                policy_version=policy_version,
                now=now,
            )
            if r:
                eligible_ranked.append(r)
        elif elig == "Needs review" and include_needs_review:
            r = rank_match(
                m,
                verified_resume_text=verified_resume_text,
                policy_version=policy_version,
                now=now,
            )
            if r:
                review_ranked.append(r)

    eligible_ranked.sort(
        key=lambda r: (
            -float(r["scores"]["priority"]),
            -float(r["scores"]["profile_fit"]),
            r["job_key"],
        )
    )
    review_ranked.sort(
        key=lambda r: (
            -float(r["scores"]["priority"]),
            -float(r["scores"]["profile_fit"]),
            r["job_key"],
        )
    )

    shortlist: list[dict[str, Any]] = []
    for i, r in enumerate(eligible_ranked, start=1):
        r["rank"] = i
        if i <= shortlist_size:
            r["shortlist"] = True
            r["queue"] = "shortlist"
            shortlist.append(r)
        else:
            r["shortlist"] = False
            r["queue"] = "ranked"
        validate(r, "ranked-opportunity.schema.json")

    for i, r in enumerate(review_ranked, start=1):
        r["rank"] = i
        r["shortlist"] = False
        r["queue"] = "human_review"
        validate(r, "ranked-opportunity.schema.json")

    return {
        "shortlist": shortlist,
        "human_review": review_ranked,
        "ranked_eligible": eligible_ranked,
        "shortlist_size": shortlist_size,
        "eligible_count": len(eligible_ranked),
        "needs_review_count": len(review_ranked),
        "policy_version": policy_version,
    }


def enrich_handoff_with_ranking(
    state: MutableMapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    """Attach ranking summary + per-match scores onto handoff-state (compat-preserving)."""
    by_key = {
        r["job_key"]: r
        for r in list(result.get("ranked_eligible") or [])
        + list(result.get("human_review") or [])
    }
    matches = state.get("matches")
    if isinstance(matches, list):
        for m in matches:
            if not isinstance(m, dict):
                continue
            jk = str(m.get("job_key") or job_key_from_url(str(m.get("canonical_url") or "")))
            ranked = by_key.get(jk)
            if not ranked:
                continue
            m["rank"] = ranked["rank"]
            m["shortlist"] = ranked["shortlist"]
            m["ranking"] = {
                "scores": ranked["scores"],
                "queue": ranked["queue"],
                "gaps": ranked.get("gaps") or [],
            }
    state["ranking"] = {
        "shortlist_count": len(result.get("shortlist") or []),
        "eligible_count": result.get("eligible_count"),
        "needs_review_count": result.get("needs_review_count"),
        "shortlist_job_keys": [r["job_key"] for r in (result.get("shortlist") or [])],
        "policy_version": result.get("policy_version"),
    }
    attach_eligible_count(state)


def rank_handoff_state(
    state: MutableMapping[str, Any],
    *,
    run_id: str,
    include_needs_review: bool = True,
    shortlist_size: int = SHORTLIST_SIZE,
    verified_resume_text: str = "",
    ledger: Optional[Ledger] = None,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    matches = state.get("matches") if isinstance(state.get("matches"), list) else []
    result = rank_opportunities(
        matches,
        include_needs_review=include_needs_review,
        shortlist_size=shortlist_size,
        verified_resume_text=verified_resume_text,
        policy_version=policy_version,
    )
    enrich_handoff_with_ranking(state, result)

    artifact = {
        "run_id": run_id,
        "shortlist": result["shortlist"],
        "human_review": result["human_review"],
        "ranked_eligible": result["ranked_eligible"],
        "shortlist_size": shortlist_size,
        "eligible_count": result["eligible_count"],
        "needs_review_count": result["needs_review_count"],
        "policy_version": policy_version,
        "certainty_note": (
            "Scores are deterministic profile-fit / keyword-overlap / SOP §13 "
            "interview-opportunity components. No fictional percent certainty."
        ),
    }

    if ledger is not None:
        env = make_envelope(
            run_id=run_id,
            producer=PRODUCER,
            artifact_type=ARTIFACT_TYPE,
            payload={
                "shortlist": artifact["shortlist"],
                "human_review_count": artifact["needs_review_count"],
                "eligible_count": artifact["eligible_count"],
            },
            task_id=f"{run_id}:rank",
            status="ok",
            evidence_refs=[r["canonical_url"] for r in artifact["shortlist"][:5]],
        )
        ledger.append_artifact(env)
        for r in artifact["shortlist"]:
            ledger.transition_job(
                r["job_key"],
                canonical_url=r["canonical_url"],
                status="Eligible",
                run_id=run_id,
                organization=r.get("organization") or "",
                role=r.get("role") or "",
                country=r.get("country") or "",
                lane=r.get("lane"),
                meta={"ranking": r["scores"], "shortlist": True},
            )

    return artifact


def _cli() -> int:
    ap = argparse.ArgumentParser(description="JobOps F04 rank_opportunities (I01–I04)")
    ap.add_argument("--state", required=True, help="handoff-state.json path")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", default="", help="ranked shortlist artifact JSON")
    ap.add_argument("--db", default="", help="SQLite ledger path (optional)")
    ap.add_argument("--shortlist-size", type=int, default=SHORTLIST_SIZE)
    ap.add_argument("--no-needs-review", action="store_true")
    ap.add_argument("--verified-text", default="", help="optional verified resume extract")
    args = ap.parse_args()

    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    ledger: Optional[Ledger] = Ledger(args.db) if args.db else None

    artifact = rank_handoff_state(
        state,
        run_id=args.run_id,
        include_needs_review=not args.no_needs_review,
        shortlist_size=args.shortlist_size,
        verified_resume_text=args.verified_text,
        ledger=ledger,
    )

    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    out_path = Path(args.out) if args.out else state_path.parent / "ranked-shortlist.json"
    out_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")

    if ledger:
        ledger.set_phase(args.run_id, "ranked")
        ledger.mark_task(
            f"{args.run_id}:rank",
            args.run_id,
            "rank",
            "complete",
            finished=True,
            detail={
                "shortlist_count": len(artifact["shortlist"]),
                "eligible_count": artifact["eligible_count"],
            },
        )
        ledger.close()

    summary = {
        "ok": True,
        "run_id": args.run_id,
        "shortlist_count": len(artifact["shortlist"]),
        "eligible_count": artifact["eligible_count"],
        "needs_review_count": artifact["needs_review_count"],
        "out": str(out_path),
        "shortlist_job_keys": [r["job_key"] for r in artifact["shortlist"]],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
