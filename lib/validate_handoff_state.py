#!/usr/bin/env python3
"""Validate handoff-state.json for the local job-apply harness."""
from __future__ import annotations

import json
import sys
from pathlib import Path


FLOOR_DEFAULT = 100


def fail(msg: str) -> int:
    print(f"INVALID: {msg}", file=sys.stderr)
    return 2


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        return fail("usage: validate_handoff_state.py <handoff-state.json> [floor]")

    path = Path(sys.argv[1])
    expected_floor = int(sys.argv[2]) if len(sys.argv) == 3 else FLOOR_DEFAULT
    if not path.is_file():
        return fail(f"missing file: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return fail(f"JSON parse error: {exc}")

    if not isinstance(data, dict):
        return fail("root must be an object")

    floor = data.get("floor")
    if floor != expected_floor:
        return fail(f"floor must be {expected_floor}, got {floor!r}")

    matches = data.get("matches")
    if not isinstance(matches, list):
        return fail("matches must be a list")

    try:
        cumulative = int(data.get("cumulative_handoff_matches"))
    except (TypeError, ValueError):
        return fail("cumulative_handoff_matches must be an int")

    if cumulative != len(matches):
        return fail(
            f"cumulative_handoff_matches ({cumulative}) != len(matches) ({len(matches)})"
        )

    floor_met = data.get("floor_met")
    if not isinstance(floor_met, bool):
        return fail("floor_met must be a boolean")
    if floor_met != (cumulative >= expected_floor):
        return fail(
            f"floor_met={floor_met} inconsistent with cumulative={cumulative} floor={expected_floor}"
        )

    urls = []
    eligible_count = 0
    for i, item in enumerate(matches):
        if not isinstance(item, dict):
            return fail(f"matches[{i}] must be an object")
        url = item.get("canonical_url")
        status = item.get("status")
        if not isinstance(url, str) or not url.startswith("http"):
            return fail(f"matches[{i}].canonical_url must be an http(s) URL")
        if not isinstance(status, str) or not status.strip():
            return fail(f"matches[{i}].status must be a non-empty string")
        if status.strip().lower() == "eligible":
            eligible_count += 1
        urls.append(url)
    if len(urls) != len(set(urls)):
        return fail("matches contain duplicate canonical_url values")

    # Prefer explicit eligible_count when present; otherwise derive it.
    if "eligible_count" in data:
        try:
            stated = int(data.get("eligible_count"))
        except (TypeError, ValueError):
            return fail("eligible_count must be an int when present")
        if stated != eligible_count:
            return fail(
                f"eligible_count ({stated}) != counted Eligible matches ({eligible_count})"
            )

    tried = data.get("sources_tried")
    remaining = data.get("sources_remaining_readable")
    blocked = data.get("sources_blocked")
    if not isinstance(tried, list):
        return fail("sources_tried must be a list")
    if not isinstance(remaining, list):
        return fail("sources_remaining_readable must be a list")
    if not isinstance(blocked, list):
        return fail("sources_blocked must be a list")

    exhausted = data.get("readable_sources_exhausted")
    if not isinstance(exhausted, bool):
        return fail("readable_sources_exhausted must be a boolean")

    if exhausted:
        if remaining:
            return fail(
                "readable_sources_exhausted=true but sources_remaining_readable is non-empty"
            )
        if not tried:
            return fail(
                "readable_sources_exhausted=true requires a non-empty sources_tried"
            )

    run_id = data.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return fail("run_id must be a non-empty string")

    phase = data.get("phase")
    if phase not in {"discovery", "post-discovery", "complete"}:
        return fail("phase must be discovery|post-discovery|complete")

    # Decision for the shell harness.
    if floor_met or exhausted:
        decision = "ACCEPT"
        reason = "floor_met" if floor_met else "sources_exhausted"
    elif remaining:
        decision = "CONTINUE"
        reason = f"below_floor_with_{len(remaining)}_sources_remaining"
    else:
        # Below floor, no remaining listed, not marked exhausted → agent must fix state.
        decision = "REJECT"
        reason = "below_floor_without_remaining_or_exhausted_flag"

    print(
        json.dumps(
            {
                "ok": decision != "REJECT",
                "decision": decision,
                "reason": reason,
                "run_id": run_id,
                "cumulative_handoff_matches": cumulative,
                "eligible_count": eligible_count,
                "floor": expected_floor,
                "floor_met": floor_met,
                "readable_sources_exhausted": exhausted,
                "sources_tried": len(tried),
                "sources_remaining_readable": len(remaining),
                "phase": phase,
            }
        )
    )
    return 0 if decision != "REJECT" else 2


if __name__ == "__main__":
    sys.exit(main())
