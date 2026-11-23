#!/usr/bin/env python3
"""F10 R01 — Tracker Synchronizer: idempotent ledger → Sheets row adapter (offline plan OK)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import POLICY_VERSION, content_hash, utc_now_iso  # noqa: E402
from ledger import Ledger  # noqa: E402

PRODUCER = "sheets_sync"
LIVE_CREDS_ENV = "GOOGLE_APPLICATION_CREDENTIALS"


def sheets_row_key(job_key: str, *, tab: str = "ranked_opportunities") -> str:
    """Stable idempotent key for a Sheets row (replay-safe)."""
    return f"{tab}:{job_key}"


def job_to_row(job: Mapping[str, Any], *, tab: str = "ranked_opportunities") -> dict[str, Any]:
    jk = str(job.get("job_key") or "")
    return {
        "row_key": sheets_row_key(jk, tab=tab),
        "tab": tab,
        "job_key": jk,
        "canonical_url": job.get("canonical_url") or "",
        "organization": job.get("organization") or "",
        "role": job.get("role") or "",
        "status": job.get("status") or "",
        "country": job.get("country") or "",
        "lane": job.get("lane") or "",
        "updated_at": job.get("updated_at") or utc_now_iso(),
        "content_hash": content_hash(
            {
                "job_key": jk,
                "status": job.get("status"),
                "canonical_url": job.get("canonical_url"),
                "organization": job.get("organization"),
                "role": job.get("role"),
            }
        ),
    }


def list_ledger_jobs(ledger: Ledger) -> list[dict[str, Any]]:
    rows = ledger._conn.execute(  # noqa: SLF001
        """
        SELECT job_key, canonical_url, organization, role, status, country, lane,
               updated_at, last_run_id, meta_json
        FROM jobs ORDER BY job_key
        """
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["meta"] = json.loads(d.pop("meta_json") or "{}")
        except json.JSONDecodeError:
            d["meta"] = {}
        out.append(d)
    return out


def build_sync_plan(
    jobs: Sequence[Mapping[str, Any]],
    *,
    prior_row_keys: Optional[set[str]] = None,
    tab: str = "ranked_opportunities",
) -> dict[str, Any]:
    """
    Build an idempotent sync plan. Replaying the same jobs yields the same row_keys.
    Updates vs inserts decided by prior_row_keys (from previous plan or Sheets mirror).
    """
    prior = set(prior_row_keys or [])
    rows = [job_to_row(j, tab=tab) for j in jobs if j.get("job_key")]
    inserts = []
    updates = []
    for row in rows:
        if row["row_key"] in prior:
            updates.append(row)
        else:
            inserts.append(row)
    # Stable ordering for deterministic replay.
    rows_sorted = sorted(rows, key=lambda r: r["row_key"])
    plan = {
        "ok": True,
        "producer": PRODUCER,
        "tab": tab,
        "integration": "offline_plan",
        "live_api": False,
        "live_sheets_implemented": False,
        "reason": "offline_plan_helper_only — Google Sheets API not invoked",
        "created_at": utc_now_iso(),
        "policy_version": POLICY_VERSION,
        "row_count": len(rows_sorted),
        "insert_count": len(inserts),
        "update_count": len(updates),
        "row_keys": [r["row_key"] for r in rows_sorted],
        "rows": rows_sorted,
        "inserts": sorted(inserts, key=lambda r: r["row_key"]),
        "updates": sorted(updates, key=lambda r: r["row_key"]),
    }
    return plan


def plan_from_ledger(
    ledger: Ledger,
    *,
    prior_plan_path: Optional[Path] = None,
    tab: str = "ranked_opportunities",
) -> dict[str, Any]:
    prior_keys: set[str] = set()
    if prior_plan_path and Path(prior_plan_path).is_file():
        prior = json.loads(Path(prior_plan_path).read_text(encoding="utf-8"))
        prior_keys = set(prior.get("row_keys") or [])
    jobs = list_ledger_jobs(ledger)
    return build_sync_plan(jobs, prior_row_keys=prior_keys, tab=tab)


def replay_row_keys(plan: Mapping[str, Any]) -> list[str]:
    return list(plan.get("row_keys") or [])


def live_sheets_available() -> bool:
    """True only when GOOGLE_APPLICATION_CREDENTIALS points to an existing file."""
    import os

    path = os.environ.get(LIVE_CREDS_ENV) or ""
    return bool(path) and Path(path).is_file()


def sync_or_plan(
    ledger: Ledger,
    *,
    out_path: Path,
    prior_plan_path: Optional[Path] = None,
    force_offline: bool = True,
) -> dict[str, Any]:
    """
    Prefer offline sync plan. Live Sheets append is optional and skipped without creds.
    Tests must never require live Google credentials.
    """
    plan = plan_from_ledger(ledger, prior_plan_path=prior_plan_path)
    creds = live_sheets_available()
    # Truthful status: offline planning helper is implemented; live Sheets API is not.
    plan["live_sheets_implemented"] = False
    plan["credentials_present"] = creds
    if force_offline or not creds:
        plan["integration"] = "offline_plan"
        plan["live_api"] = False
        plan["reason"] = "offline_plan_helper_only — no live Google Sheets sync"
    else:
        plan["integration"] = "offline_plan"
        plan["live_api"] = False
        plan["reason"] = (
            "credentials present but live Google Sheets adapter is not implemented; "
            "emitting offline plan only"
        )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def _cli() -> int:
    ap = argparse.ArgumentParser(description="R01 Sheets sync planner (offline-safe)")
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prior-plan", default="")
    ap.add_argument("--tab", default="ranked_opportunities")
    args = ap.parse_args()
    led = Ledger(args.db)
    try:
        plan = sync_or_plan(
            led,
            out_path=Path(args.out),
            prior_plan_path=Path(args.prior_plan) if args.prior_plan else None,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "row_count": plan["row_count"],
                    "row_keys": plan["row_keys"],
                    "live_api": plan["live_api"],
                    "out": args.out,
                },
                indent=2,
            )
        )
        return 0
    finally:
        led.close()


if __name__ == "__main__":
    raise SystemExit(_cli())
