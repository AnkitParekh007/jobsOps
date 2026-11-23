#!/usr/bin/env python3
"""Review-first public ATS workflow. No submission, outreach or inferred eligibility."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from live_discovery import Source, discover, load_sources, safe_http_fetch
from ledger import Ledger

MAX_ROLE_FILTERS = 25
MAX_QUEUE = 500
_SOURCE_HOSTS = frozenset({"boards-api.greenhouse.io", "api.lever.co", "api.eu.lever.co"})
_UNRESOLVED = (
    "country_and_work_authorization_not_confirmed",
    "visa_sponsorship_not_confirmed",
    "remote_onsite_and_travel_requirements_not_confirmed",
    "mandatory_qualifications_not_confirmed",
    "posting_requires_freshness_recheck_before_apply",
)
_WORD = re.compile(r"[a-z0-9][a-z0-9+#.-]*")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.casefold()))


def build_review_queue(
    discovery: dict[str, Any], *,
    role_keywords: tuple[str, ...] = (),
    max_queue: int = MAX_QUEUE,
) -> dict[str, Any]:
    """Create a queue, never a clearance or submission authorization.

    Only source-verified listings from the live discovery adapter can enter.
    Scoring is *query relevance*, never ATS score or candidate eligibility.
    """
    if discovery.get("mode") != "public_ats_read_only" or discovery.get("submit_enabled") is not False:
        raise ValueError("untrusted_discovery_report")
    if discovery.get("outreach_enabled") is not False:
        raise ValueError("outreach_must_be_disabled")
    if not 1 <= max_queue <= MAX_QUEUE or len(role_keywords) > MAX_ROLE_FILTERS:
        raise ValueError("invalid_queue_limits")
    normalized = [w.strip().casefold() for w in role_keywords if w.strip()]
    if any(len(w) > 80 for w in normalized):
        raise ValueError("role_filter_too_long")
    queue: list[dict[str, Any]] = []
    dropped = 0
    seen: set[str] = set()
    for item in discovery.get("jobs", []):
        if not isinstance(item, dict):
            dropped += 1
            continue
        if (item.get("availability") != "open"
                or item.get("availability_evidence") != "present_in_current_public_ats_feed"
                or item.get("eligibility") != "Needs review"):
            dropped += 1
            continue
        src = str(item.get("source_url") or "")
        canonical = str(item.get("canonical_url") or "")
        if (urlsplit(src).scheme != "https"
                or urlsplit(src).hostname not in _SOURCE_HOSTS
                or urlsplit(canonical).scheme != "https"):
            dropped += 1
            continue
        digest = str(item.get("source_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            dropped += 1
            continue
        key = str(item.get("job_key") or "")
        if not key or key in seen:
            dropped += 1
            continue
        seen.add(key)
        title = str(item.get("role") or "")
        title_tokens = _tokens(title)
        matching = [term for term in normalized if _tokens(term) and _tokens(term).issubset(title_tokens)]
        if normalized and not matching:
            continue
        queue.append({
            "job_key": key,
            "organization": str(item.get("organization") or ""),
            "role": title,
            "location_text": str(item.get("location_text") or ""),
            "canonical_url": canonical,
            "source": str(item.get("source") or ""),
            "source_url": src,
            "fetched_at": item.get("fetched_at"),
            "source_sha256": digest,
            "availability_evidence": item["availability_evidence"],
            "decision": "Needs review",
            "queue": "human_review",
            "matched_role_keywords": matching,
            "query_relevance_count": len(matching),
            "blocking_reasons": list(_UNRESOLVED),
            "evidence_refs": [src, canonical],
            "next_action": "Manually verify live ATS posting, eligibility, remote policy and consent.",
        })
    queue.sort(key=lambda x: (-x["query_relevance_count"], x["organization"].casefold(),
                              x["job_key"]))
    limited = queue[:max_queue]
    return {
        "schema": "jobops-review-queue-v1",
        "run_id": discovery.get("run_id"),
        "created_at": discovery.get("created_at"),
        "mode": "review_only",
        "source_states": discovery.get("sources", []),
        "queue": limited,
        "counts": {"discovered": len(discovery.get("jobs", [])), "review": len(limited),
                   "filtered_or_truncated": max(0, len(queue) - len(limited)),
                   "rejected_untrusted": dropped,
                   "blocked_sources": discovery.get("counts", {}).get("blocked", 0),
                   "partial_sources": discovery.get("counts", {}).get("partial", 0)},
        "eligibility_cleared": 0,
        "submissions": 0,
        "outreach_sends": 0,
        "production_certified": False,
        "limitations": [
            "No independent browser/ATS availability recheck",
            "No candidate-specific eligibility clearance",
            "No authenticated live submission or outreach",
        ],
    }


def run_review(
    sources: list[Source], *,
    fetch: Callable[[str], tuple[int, str]] = safe_http_fetch,
    ledger: Optional[Ledger] = None,
    role_keywords: tuple[str, ...] = (),
    max_jobs: int = 250,
    max_queue: int = MAX_QUEUE,
    delay_seconds: float = 0.5,
) -> dict[str, Any]:
    report = discover(sources, fetch=fetch, ledger=ledger, max_jobs=max_jobs,
                      delay_seconds=delay_seconds)
    return build_review_queue(report, role_keywords=role_keywords, max_queue=max_queue)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only public ATS research-to-review queue")
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--role-keyword", action="append", default=[])
    parser.add_argument("--max-jobs", type=int, default=250)
    parser.add_argument("--max-queue", type=int, default=MAX_QUEUE)
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args(argv)
    try:
        sources = load_sources(args.sources)
        if not any(s.enabled for s in sources):
            raise ValueError("no_enabled_sources")
        ledger = Ledger(args.ledger) if args.ledger else None
        try:
            result = run_review(sources, ledger=ledger,
                                role_keywords=tuple(args.role_keyword),
                                max_jobs=args.max_jobs, max_queue=args.max_queue,
                                delay_seconds=args.delay)
        finally:
            if ledger:
                ledger.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        print(json.dumps({"ok": True, "report": str(args.output),
                          "counts": result["counts"], "mode": "review_only"}))
        return 1 if result["counts"]["blocked_sources"] or result["counts"]["partial_sources"] else 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
