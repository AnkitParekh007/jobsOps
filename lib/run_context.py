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
    DAILY_SUBMIT_CAP,
    HANDOFF_FLOOR_DEFAULT,
)
from user_workspace import (  # noqa: E402
    default_jobops_home,
    load_candidate_profile,
    workspace_paths,
)


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
    workspace_home: Optional[Path] = None,
    require_profile: bool = False,
) -> dict[str, Any]:
    """
    Build RunContext from private user workspace facts — never hardcoded biography.
    """
    home = Path(workspace_home) if workspace_home else default_jobops_home()
    profile = load_candidate_profile(
        home=home,
        notes_path=Path(notes_path) if notes_path else None,
        allow_missing=not require_profile,
    )
    prefs = dict(profile.preferences)
    prefs["daily_submit_cap"] = int(prefs.get("daily_submit_cap") or DAILY_SUBMIT_CAP)
    prefs["handoff_floor"] = int(floor)
    sponsorship = prefs.get("sponsorship_required_countries")
    if not isinstance(sponsorship, list):
        sponsorship = []

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

        exclusion = _exclusion_counts(exclusion_path, led)

        # Portal inventory from profile hints only — status remains unknown until verified.
        portals = []
        for name in ("Greenhouse", "Ashby", "Lever", "LinkedIn", "Gmail"):
            hint = None
            acct = (profile.portal_accounts or {}).get(name.lower()) or (
                profile.portal_accounts or {}
            ).get(name)
            if isinstance(acct, dict):
                hint = acct.get("account_hint")
            elif isinstance(acct, str) and acct:
                hint = "configured"
            portals.append({"portal": name, "status": "unknown", "account_hint": hint})

        session_inventory = {
            "portals": portals,
            "unknown_allowed": True,
        }

        gates = {
            "sheet_append_proven": False,
            "discovery_allowed": lock_acquired and (
                bool(profile.verified_facts) or not require_profile
            ),
            "profile_loaded": profile.loaded,
            "auto_submit_enabled": bool(profile.consent.get("auto_submit_enabled")),
            "outreach_send_enabled": bool(profile.consent.get("outreach_send_enabled")),
            "notes": [
                "Run row + lock acquired (or abort).",
                "Candidate facts loaded from private JOBOPS_HOME only.",
                "Never record Applied without receipt.",
                "Submit and outreach send disabled unless consent explicitly enables them.",
            ],
        }
        if profile.missing_reasons:
            gates["notes"].append("profile_gaps: " + ", ".join(profile.missing_reasons))

        if not lock_acquired:
            gates["discovery_allowed"] = False
            raise SystemExit("run_context: run lock not acquired — aborting")

        ws = workspace_paths(home)
        ctx: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "created_at": utc_now_iso(),
            "policy_version": POLICY_VERSION,
            "verified_facts": {
                "source_urls": list(profile.resume_urls),
                "facts": list(profile.verified_facts),
                "contradictions": [],
                "notes_path": profile.source_path,
                "identity_markers": list(profile.identity_markers),
                "display_name": profile.display_name,
                "workspace_home": str(ws["home"]),
            },
            "preferences": {
                "country_priority": list(prefs.get("country_priority") or ["Remote"]),
                "sponsorship_required_countries": list(sponsorship),
                "daily_submit_cap": int(prefs["daily_submit_cap"]),
                "handoff_floor": floor,
                "india_remote_only": bool(prefs.get("india_remote_only")),
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

        evidence_refs = list(profile.resume_urls)
        if profile.source_path:
            evidence_refs.append(profile.source_path)
        env = make_envelope(
            run_id=run_id,
            producer="f01_run_context",
            artifact_type="run_context",
            payload=ctx,
            task_id=f"{run_id}:context",
            evidence_refs=evidence_refs or [f"workspace:{ws['home']}"],
        )
        led.append_artifact(env)
        led.mark_task(
            f"{run_id}:context",
            run_id,
            "context",
            "complete",
            finished=True,
            detail={"lock_id": lock_id, "profile_loaded": profile.loaded},
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
    ap.add_argument("--workspace", default="", help="JOBOPS_HOME override")
    ap.add_argument("--require-profile", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out", default="", help="override run-context.json path")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    exclusion = Path(args.exclusion) if args.exclusion else None
    notes = Path(args.notes) if args.notes else None
    home = Path(args.workspace) if args.workspace else None

    ctx = build_run_context(
        run_id=args.run_id,
        floor=args.floor,
        exclusion_path=exclusion,
        notes_path=notes,
        db_path=Path(args.db),
        acquire_lock=True,
        workspace_home=home,
        require_profile=args.require_profile,
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
                "profile_loaded": bool((ctx.get("gates") or {}).get("profile_loaded")),
                "fact_count": len((ctx.get("verified_facts") or {}).get("facts") or []),
                "daily_submit_cap": DAILY_SUBMIT_CAP,
                "handoff_floor": args.floor,
                "workspace_home": (ctx.get("verified_facts") or {}).get("workspace_home"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
