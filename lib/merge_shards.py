#!/usr/bin/env python3
"""Merge discovery worker shards into handoff-state.json (mechanical floor)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


FLOOR_DEFAULT = 100
IST = ZoneInfo("Asia/Kolkata")


def die(msg: str) -> None:
    print(f"merge_shards ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        die(f"{path}: {exc}")
    if not isinstance(data, dict):
        die(f"{path}: root must be an object")
    return data


def normalize_match(raw: dict, shard_id: str) -> dict | None:
    url = raw.get("canonical_url")
    status = raw.get("status")
    if not isinstance(url, str) or not url.startswith("http"):
        return None
    if not isinstance(status, str) or not status.strip():
        return None
    # Early duplicates / lane misses must not be counted by workers either.
    if status.strip().lower() in {"duplicate"}:
        return None
    out = {
        "canonical_url": url.split("?")[0].rstrip("/"),
        "organization": raw.get("organization") or "",
        "role": raw.get("role") or "",
        "status": status.strip(),
        "lane": raw.get("lane"),
        "country": raw.get("country") or "",
        "source": raw.get("source") or "",
        "shard_id": shard_id,
        "employer_or_ats_url": raw.get("employer_or_ats_url") or url,
        # Preserve discovery evidence for downstream verify/rank (Phase 0).
        "reason": raw.get("reason") if isinstance(raw.get("reason"), str) else "",
    }
    evidence = raw.get("evidence_quote")
    if isinstance(evidence, str) and evidence.strip():
        out["evidence_quote"] = evidence.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--floor", type=int, default=FLOOR_DEFAULT)
    ap.add_argument("--exclusion", default="", help="JSON file with excluded canonical URLs")
    args = ap.parse_args()

    shards_dir = Path(args.shards_dir)
    if not shards_dir.is_dir():
        die(f"shards dir missing: {shards_dir}")

    excluded: set[str] = set()
    if args.exclusion:
        ex_path = Path(args.exclusion)
        if ex_path.is_file():
            payload = load_json(ex_path)
            for u in payload.get("canonical_urls") or []:
                if isinstance(u, str) and u.startswith("http"):
                    excluded.add(u.split("?")[0].rstrip("/"))

    shard_files = sorted(shards_dir.glob("*.json"))
    if not shard_files:
        die(f"no shard JSON files in {shards_dir}")

    matches: list[dict] = []
    seen: set[str] = set()
    sources_tried: list[str] = []
    sources_blocked: list[dict] = []
    sources_remaining: list[str] = []
    shard_summaries: list[dict] = []
    all_exhausted = True

    for path in shard_files:
        data = load_json(path)
        shard_id = data.get("shard_id") or path.stem
        exhausted = bool(data.get("exhausted"))
        if not exhausted:
            all_exhausted = False

        for s in data.get("sources_tried") or []:
            if isinstance(s, str) and s not in sources_tried:
                sources_tried.append(s)
        for b in data.get("sources_blocked") or []:
            if isinstance(b, dict) and b not in sources_blocked:
                sources_blocked.append(b)
        for s in data.get("sources_remaining_readable") or []:
            if isinstance(s, str) and s not in sources_remaining:
                sources_remaining.append(s)

        added = 0
        skipped_excl = 0
        skipped_dup = 0
        for raw in data.get("matches") or []:
            if not isinstance(raw, dict):
                continue
            m = normalize_match(raw, str(shard_id))
            if not m:
                continue
            url = m["canonical_url"]
            if url in excluded:
                skipped_excl += 1
                continue
            if url in seen:
                skipped_dup += 1
                continue
            seen.add(url)
            matches.append(m)
            added += 1

        shard_summaries.append(
            {
                "shard_id": shard_id,
                "path": str(path),
                "exhausted": exhausted,
                "matches_accepted": added,
                "skipped_exclusion": skipped_excl,
                "skipped_in_merge_dup": skipped_dup,
            }
        )

    cumulative = len(matches)
    floor_met = cumulative >= args.floor
    # Exhaustion only if every shard exhausted AND nothing readable remains.
    readable_sources_exhausted = all_exhausted and not sources_remaining

    if floor_met:
        phase = "post-discovery"
    elif readable_sources_exhausted:
        phase = "post-discovery"
    else:
        phase = "discovery"

    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M Asia/Calcutta")
    state = {
        "run_id": args.run_id,
        "floor": args.floor,
        "cumulative_handoff_matches": cumulative,
        "floor_met": floor_met,
        "readable_sources_exhausted": readable_sources_exhausted,
        "sources_tried": sources_tried,
        "sources_blocked": sources_blocked,
        "sources_remaining_readable": [] if readable_sources_exhausted else sources_remaining,
        "matches": matches,
        "updated_at_asia_calcutta": now,
        "phase": phase,
        "merge": {
            "shards": shard_summaries,
            "excluded_url_count": len(excluded),
        },
    }

    out = Path(args.out)
    out.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    summary = {
        "out": str(out),
        "cumulative_handoff_matches": cumulative,
        "floor": args.floor,
        "floor_met": floor_met,
        "readable_sources_exhausted": readable_sources_exhausted,
        "shards": len(shard_files),
        "phase": phase,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
