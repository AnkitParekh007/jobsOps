#!/usr/bin/env python3
"""Phase 5: opt-in, read-only discovery from public ATS posting APIs.

Never interprets a listing as proof of sponsorship, work rights or eligibility.
Never fetches arbitrary URLs supplied by the ATS response.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.parse import urlsplit

from contracts import make_envelope, utc_now_iso
from ledger import Ledger
from url_safety import safe_http_fetch, validate_fetch_url

IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")
ALLOWED_PROVIDERS = frozenset({"greenhouse", "lever", "lever_eu"})
MAX_SOURCES = 20
MAX_JOBS_PER_SOURCE = 250
MAX_DESCRIPTION = 6000
Fetch = Callable[[str], tuple[int, str]]


class FeedError(ValueError):
    pass


class TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: Any) -> str:
    parser = TextOnly()
    parser.feed(html.unescape(str(value or ""))[:200000])
    return " ".join(" ".join(parser.parts).split())[:MAX_DESCRIPTION]


@dataclass(frozen=True)
class Source:
    provider: str
    board: str
    organization: str
    enabled: bool = True

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.board.lower()}"

    @property
    def endpoint(self) -> str:
        if self.provider == "greenhouse":
            return f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs?content=true"
        host = "api.eu.lever.co" if self.provider == "lever_eu" else "api.lever.co"
        return f"https://{host}/v0/postings/{self.board}?mode=json"


def load_sources(path: Path) -> list[Source]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("sources"), list):
        raise FeedError("source_registry_requires_sources_array")
    if len(raw["sources"]) > MAX_SOURCES:
        raise FeedError("source_registry_too_large")
    found: set[str] = set()
    result: list[Source] = []
    for item in raw["sources"]:
        if not isinstance(item, dict):
            raise FeedError("invalid_source")
        provider, board = item.get("provider"), item.get("board")
        organization = item.get("organization")
        if provider not in ALLOWED_PROVIDERS or not isinstance(board, str) or not IDENTIFIER.fullmatch(board):
            raise FeedError("untrusted_source_provider_or_board")
        if not isinstance(organization, str) or not organization.strip() or len(organization) > 120:
            raise FeedError("source_organization_required")
        if item.get("enabled", True) not in {True, False}:
            raise FeedError("source_enabled_must_be_boolean")
        src = Source(provider, board, organization.strip(), item.get("enabled", True))
        if src.key in found:
            raise FeedError("duplicate_source")
        found.add(src.key)
        result.append(src)
    return result


def _approved_job_url(url: Any, provider: str) -> Optional[str]:
    if not isinstance(url, str) or len(url) > 2000:
        return None
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    hosts = {
        "greenhouse": {"boards.greenhouse.io", "job-boards.greenhouse.io"},
        "lever": {"jobs.lever.co"},
        "lever_eu": {"jobs.eu.lever.co", "jobs.lever.co"},
    }[provider]
    if parsed.scheme != "https" or host not in hosts or parsed.username or parsed.password:
        return None
    if not validate_fetch_url(url, resolve_dns=False).ok:
        return None
    # Strip URL fragments and marketing query parameters; never fetch the link.
    return f"https://{host}{parsed.path.rstrip('/') or '/'}"


def _job_from_api(item: Mapping[str, Any], src: Source, endpoint: str, fetched: str, digest: str) -> Optional[dict[str, Any]]:
    if src.provider == "greenhouse":
        job_id, title = item.get("id"), item.get("title")
        url = item.get("absolute_url")
        loc = item.get("location") or {}
        location = loc.get("name", "") if isinstance(loc, dict) else ""
        description = item.get("content") or ""
    else:
        job_id, title = item.get("id"), item.get("text")
        url = item.get("hostedUrl")
        cat = item.get("categories") or {}
        location = cat.get("location", "") if isinstance(cat, dict) else ""
        description = item.get("descriptionPlain") or item.get("description") or ""
    if not isinstance(job_id, (int, str)) or not str(job_id).strip() or not isinstance(title, str) or not title.strip():
        return None
    canonical = _approved_job_url(url, src.provider)
    if not canonical:
        return None
    stable = f"{src.provider}:{src.board.lower()}:{str(job_id).strip()}"
    body = plain_text(description)
    return {
        "job_key": stable,
        "requisition_id": str(job_id),
        "canonical_url": canonical,
        "employer_or_ats_url": canonical,
        "organization": src.organization,
        "role": title.strip()[:200],
        "location_text": plain_text(location)[:240],
        "source": src.key,
        "source_url": endpoint,
        "fetched_at": fetched,
        "source_sha256": digest,
        "posting_text": body,
        "evidence_quote": body[:300],
        "availability": "open",
        "availability_evidence": "present_in_current_public_ats_feed",
        "eligibility": "Needs review",
        "blocking_reasons": [
            "country_work_rights_unverified",
            "sponsorship_unverified",
            "remote_and_travel_policy_unverified",
            "mandatory_requirements_unverified",
        ],
        "evidence_refs": [endpoint, canonical],
    }


def read_prior_keys(ledger: Ledger) -> set[str]:
    keys = ledger.prior_job_keys()
    rows = ledger._conn.execute(
        "SELECT payload_json FROM artifacts WHERE artifact_type='live_discovered_job'"
    ).fetchall()
    for row in rows:
        try:
            data = json.loads(row["payload_json"])
            if isinstance(data.get("job_key"), str):
                keys.add(data["job_key"])
        except (TypeError, ValueError):
            continue
    return keys


def discover(
    sources: list[Source],
    *,
    fetch: Fetch = safe_http_fetch,
    ledger: Optional[Ledger] = None,
    run_id: Optional[str] = None,
    max_jobs: int = MAX_JOBS_PER_SOURCE,
    delay_seconds: float = 0.5,
) -> dict[str, Any]:
    """Run bounded GET-only discovery; failures never mean exhausted.

    API listings prove publication at retrieval, not continued availability or eligibility.
    """
    if not 1 <= max_jobs <= MAX_JOBS_PER_SOURCE:
        raise FeedError("invalid_max_jobs")
    if not 0 <= delay_seconds <= 10:
        raise FeedError("invalid_delay")
    run = run_id or f"live_{uuid.uuid4().hex[:16]}"
    prior = read_prior_keys(ledger) if ledger else set()
    seen: set[str] = set()
    jobs: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    active = [s for s in sources if s.enabled]
    for index, src in enumerate(active):
        if index and delay_seconds:
            time.sleep(delay_seconds)
        endpoint = src.endpoint
        fetched = utc_now_iso()
        state: dict[str, Any] = {
            "source": src.key, "source_url": endpoint, "fetched_at": fetched,
            "status": "blocked", "exhausted": False, "read_count": 0,
            "accepted_count": 0, "duplicate_count": 0, "invalid_count": 0,
            "reason": "",
        }
        try:
            status, body = fetch(endpoint)
        except Exception as exc:  # noqa: BLE001 — source failure, never exhaustion
            state["reason"] = f"fetch_failed:{type(exc).__name__}"
            states.append(state)
            continue
        state["http_status"] = status
        if status != 200:
            state["reason"] = f"http_{status}" if status else "network_failure"
            states.append(state)
            continue
        if len(body.encode("utf-8")) > 4_000_000:
            state["reason"] = "response_too_large"
            states.append(state)
            continue
        try:
            payload = json.loads(body)
            raw_jobs = payload.get("jobs") if src.provider == "greenhouse" and isinstance(payload, dict) else payload
            if not isinstance(raw_jobs, list):
                raise ValueError("invalid_feed_shape")
        except (ValueError, TypeError) as exc:
            state["reason"] = f"invalid_feed:{type(exc).__name__}"
            states.append(state)
            continue
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        state["source_sha256"] = digest
        state["read_count"] = len(raw_jobs)
        state["status"] = "exhausted" if not raw_jobs else "complete"
        state["exhausted"] = not raw_jobs
        for raw in raw_jobs[:max_jobs]:
            job = _job_from_api(raw, src, endpoint, fetched, digest) if isinstance(raw, dict) else None
            if job is None:
                state["invalid_count"] += 1
                continue
            key = job["job_key"]
            if key in seen or key in prior:
                state["duplicate_count"] += 1
                continue
            seen.add(key)
            jobs.append(job)
            state["accepted_count"] += 1
            if ledger is not None:
                event = make_envelope(
                    run_id=run, producer="phase5_live_discovery",
                    artifact_type="live_discovered_job", job_key=key,
                    task_id=f"{run}:{key}", payload=job,
                    evidence_refs=job["evidence_refs"],
                )
                ledger.append_artifact(event)
        if len(raw_jobs) > max_jobs:
            state["status"] = "partial"
            state["reason"] = "source_job_limit"
            state["exhausted"] = False
        elif state["invalid_count"]:
            state["status"] = "partial"
            state["reason"] = "invalid_posting_records"
            state["exhausted"] = False
        states.append(state)
    return {
        "run_id": run, "created_at": utc_now_iso(), "mode": "public_ats_read_only",
        "jobs": jobs, "sources": states,
        "counts": {"new": len(jobs), "blocked": sum(s["status"] == "blocked" for s in states),
                   "partial": sum(s["status"] == "partial" for s in states),
                   "duplicates": sum(s["duplicate_count"] for s in states)},
        "submit_enabled": False, "outreach_enabled": False,
        "note": "Needs review is mandatory until independent eligibility and live URL checks.",
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only live discovery from explicitly listed public ATS boards")
    ap.add_argument("--sources", type=Path, required=True, help="JSON registry of Greenhouse/Lever board tokens")
    ap.add_argument("--output", type=Path, required=True, help="Local JSON report; do not place inside public git")
    ap.add_argument("--ledger", type=Path, default=None, help="Optional private SQLite ledger")
    ap.add_argument("--max-jobs", type=int, default=MAX_JOBS_PER_SOURCE)
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args(argv)
    try:
        sources = load_sources(args.sources)
        if not sources or not any(s.enabled for s in sources):
            raise FeedError("no_enabled_sources")
        led = Ledger(args.ledger) if args.ledger else None
        try:
            report = discover(sources, ledger=led, max_jobs=args.max_jobs, delay_seconds=args.delay)
        finally:
            if led is not None:
                led.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "report": str(args.output), "counts": report["counts"]}))
        return 0 if not report["counts"]["blocked"] and not report["counts"]["partial"] else 1
    except (FeedError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
