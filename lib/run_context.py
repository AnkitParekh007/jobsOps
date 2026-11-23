#!/usr/bin/env python3
"""F01 Context lite — deterministic preflight before discovery workers."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

_LIB = Path(__file__).resolve().parent
ROOT = _LIB.parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import (  # noqa: E402
    POLICY_VERSION,
    SCHEMA_VERSION,
    utc_now_iso,
    validate,
)
from ledger import DEFAULT_DB, Ledger  # noqa: E402
from policy import (  # noqa: E402
    COUNTRY_PRIORITY,
    DAILY_SUBMIT_CAP,
    HANDOFF_FLOOR_DEFAULT,
    SPONSORSHIP_REQUIRED,
)

RESUME_URL = "https://ankitparekh007.github.io/resume/"

# Verified facts baked from scheduled-task-prompt.md §2 (deterministic, no LLM).
BASELINE_FACTS = [
    "Location: Mumbai; immediate availability; 15+ years experience.",
    "Skills: Enterprise Angular, React, TypeScript (React/TS 5+ years).",
    "Agentic AI workflows, RAG, approvals/audit; SOP Co-Pilot at Bluemeteor.",
    "Former Forto Berlin EU Blue Card holder — not current German work authorization.",
    "India work authorization is the verified baseline.",
    "Germany, Ireland, and UAE require employer sponsorship evidence.",
    "Relocation is acceptable; relocation ≠ sponsorship proof.",
    "Do not invent Python proficiency or unstated credentials.",
]


def _load_notes(notes_path: Optional[Path]) -> tuple[list[str], Optional[str]]:
    if notes_path is None:
        # Best-effort local notes locations.
        candidates = [
            ROOT / "notes" / "verified-facts.md",
            ROOT / "verified-facts.md",
            ROOT / "local-notes.md",
        ]
        for c in candidates:
            if c.is_file():
                notes_path = c
                break
    if notes_path is None or not notes_path.is_file():
        return [], None
    text = notes_path.read_text(encoding="utf-8", errors="replace").strip()
    extra = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
    return extra[:50], str(notes_path)


def _exclusion_counts(exclusion_path: Optional[Path], ledger: Ledger) -> dict[str, Any]:
    url_count = 0
    path: Optional[str] = None
    if exclusion_path and exclusion_path.is_file():
        path = str(exclusion_path)
        try:
            data = json.loads(exclusion_path.read_text(encoding="utf-8"))
            urls = data.get("canonical_urls") or []
            url_count = len(urls) if isinstance(urls, list) else 0
        except (OSError, json.JSONDecodeError):
            url_count = 0
    prior_keys = ledger.prior_job_keys()
    return {
        "canonical_url_count": url_count,
        "prior_job_key_count": len(prior_keys),
        "path": path,
        "prior_job_keys_sample": sorted(prior_keys)[:20],
    }


def build_run_context(
    *,
    run_id: str,
    floor: int = HANDOFF_FLOOR_DEFAULT,
    exclusion_path: Optional[Path] = None,
    notes_path: Optional[Path] = None,
    db_path: Path = DEFAULT_DB,
    acquire_lock: bool = True,
) -> dict[str, Any]:
    led = Ledger(db_path)
    try:
        led.start_run(run_id, floor=floor, phase="context")
        lock_id = None
        lock_acquired = False
        if acquire_lock:
            try:
                lock_id = led.acquire_lock(f"run:{run_id}", run_id)
                lock_acquired = True
            except RuntimeError as exc:
                raise SystemExit(f"run_context: failed to acquire run lock: {exc}") from exc

        note_facts, resolved_notes = _load_notes(notes_path)
        facts = list(BASELINE_FACTS) + note_facts
        exclusion = _exclusion_counts(exclusion_path, led)

        session_inventory = {
            "portals": [
                {"portal": "Greenhouse", "status": "unknown", "account_hint": None},
                {"portal": "Ashby", "status": "unknown", "account_hint": None},
                {"portal": "Lever", "status": "unknown", "account_hint": None},
                {"portal": "LinkedIn", "status": "unknown", "account_hint": None},
                {"portal": "Gmail", "status": "unknown", "account_hint": None},
            ],
            "unknown_allowed": True,
        }

        # Phase 1: sheet append proof is deferred to Phase 4 R01.
        # Discovery may still run for local research; never record Applied without receipt.
        gates = {
            "sheet_append_proven": False,
            "discovery_allowed": lock_acquired,
            "notes": [
                "Phase 1 gate: run row + lock acquired (or abort).",
                "Tracker append proof deferred to Phase 4 R01; discovery allowed for local research only.",
                "Never record Applied without receipt.",
            ],
        }

        if not lock_acquired:
            gates["discovery_allowed"] = False
            raise SystemExit("run_context: run lock not acquired — aborting")

        ctx: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": utc_now_iso(),
            "policy_version": POLICY_VERSION,
            "verified_facts": {
                "source_urls": [RESUME_URL],
                "facts": facts,
                "contradictions": [],
                "notes_path": resolved_notes,
            },
            "preferences": {
                "country_priority": list(COUNTRY_PRIORITY),
                "sponsorship_required_countries": sorted(SPONSORSHIP_REQUIRED),
                "daily_submit_cap": DAILY_SUBMIT_CAP,
                "handoff_floor": floor,
                "india_remote_only": True,
            },
            "exclusion": {
                "canonical_url_count": exclusion["canonical_url_count"],
                "prior_job_key_count": exclusion["prior_job_key_count"],
                "path": exclusion["path"],
            },
            "session_inventory": session_inventory,
            "lock": {
                "acquired": lock_acquired,
                "lock_id": lock_id,
                "resource": f"run:{run_id}",
            },
            "gates": gates,
        }
        validate(ctx, "run-context.schema.json")

        from contracts import make_envelope

        env = make_envelope(
            run_id=run_id,
            producer="f01_run_context",
            artifact_type="run_context",
            payload=ctx,
            task_id=f"{run_id}:context",
            evidence_refs=[RESUME_URL] + ([resolved_notes] if resolved_notes else []),
        )
        led.append_artifact(env)
        led.mark_task(
            f"{run_id}:context",
            run_id,
            "context",
            "complete",
            finished=True,
            detail={"lock_id": lock_id},
        )
        led.set_phase(run_id, "context_complete")
        return ctx
    finally:
        led.close()


def write_session_inventory(run_dir: Path, ctx: Mapping[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "session-inventory.json"
    payload = {
        "run_id": ctx.get("run_id"),
        "created_at": ctx.get("created_at"),
        "session_inventory": ctx.get("session_inventory"),
        "lock": ctx.get("lock"),
        "gates": ctx.get("gates"),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Build F01 RunContext (Phase 1 lite)")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--run-dir", required=True, help="runs/<run_id>/")
    ap.add_argument("--floor", type=int, default=HANDOFF_FLOOR_DEFAULT)
    ap.add_argument("--exclusion", default="", help="exclusion-index.json path (optional at context time)")
    ap.add_argument("--notes", default="", help="optional local verified-facts notes")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out", default="", help="override run-context.json path")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    exclusion = Path(args.exclusion) if args.exclusion else None
    notes = Path(args.notes) if args.notes else None

    ctx = build_run_context(
        run_id=args.run_id,
        floor=args.floor,
        exclusion_path=exclusion,
        notes_path=notes,
        db_path=Path(args.db),
        acquire_lock=True,
    )
    out = Path(args.out) if args.out else run_dir / "run-context.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ctx, indent=2) + "\n", encoding="utf-8")
    inv = write_session_inventory(run_dir, ctx)
    print(
        json.dumps(
            {
                "ok": True,
                "run_id": args.run_id,
                "out": str(out),
                "session_inventory": str(inv),
                "lock_acquired": bool((ctx.get("lock") or {}).get("acquired")),
                "discovery_allowed": bool((ctx.get("gates") or {}).get("discovery_allowed")),
                "daily_submit_cap": DAILY_SUBMIT_CAP,
                "handoff_floor": args.floor,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
