#!/usr/bin/env python3
"""F10 R03/R04 — Enrich last-run-report metrics + reliability alerts."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import POLICY_VERSION, utc_now_iso  # noqa: E402
from ledger import Ledger  # noqa: E402
from policy import DAILY_SUBMIT_CAP, daily_submit_remaining  # noqa: E402

PRODUCER = "run_report"
DEFAULT_STUCK_LOCK_HOURS = 6
DEFAULT_MISSING_RECEIPT_HOURS = 24


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hours_ago(ts: str, *, now: Optional[datetime] = None) -> Optional[float]:
    dt = _parse_iso(ts)
    if not dt:
        return None
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 3600.0


def collect_verify_stats(verify_summary: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not verify_summary:
        return {"present": False}
    counts = verify_summary.get("counts") or verify_summary.get("by_decision") or {}
    return {
        "present": True,
        "eligible": int(counts.get("Eligible") or verify_summary.get("eligible") or 0),
        "needs_review": int(counts.get("Needs review") or counts.get("Needs Review") or 0),
        "skipped": int(counts.get("Skipped") or 0),
        "closed": int(counts.get("Closed") or 0),
        "duplicate": int(counts.get("Duplicate") or 0),
        "ambiguous": int(verify_summary.get("ambiguous_count") or 0),
        "raw": dict(counts) if isinstance(counts, dict) else {},
    }


def collect_stubbed_workers(run_dir: Path) -> list[dict[str, Any]]:
    stubs = []
    shards = run_dir / "shards"
    if not shards.is_dir():
        return stubs
    for path in sorted(shards.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        notes = str(data.get("notes") or "")
        sources = data.get("sources_tried") or []
        if "stub" in notes.lower() or sources == ["worker-failed-or-empty"]:
            stubs.append(
                {
                    "shard_id": data.get("shard_id") or path.stem,
                    "reason": notes or "stub_shard",
                    "matches": len(data.get("matches") or []),
                }
            )
    return stubs


def collect_wall_time(run_dir: Path, run_context: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Best-effort wall time from harness.log / run-context / timing JSON."""
    hooks: dict[str, Any] = {"present": False}
    # Explicit timing file if present
    for name in ("timing.json", "wall-time.json"):
        p = run_dir / name
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                hooks.update(data if isinstance(data, dict) else {})
                hooks["present"] = True
                hooks["source"] = name
                return hooks
            except json.JSONDecodeError:
                pass
    if run_context and isinstance(run_context.get("timing"), dict):
        hooks.update(run_context["timing"])
        hooks["present"] = True
        hooks["source"] = "run-context"
        return hooks
    log = run_dir / "harness.log"
    if log.is_file():
        text = log.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"elapsed_ms[=:\s]+(\d+)", text, re.I)
        if m:
            ms = int(m.group(1))
            hooks = {
                "present": True,
                "source": "harness.log",
                "elapsed_ms": ms,
                "elapsed_sec": round(ms / 1000.0, 1),
            }
            return hooks
    hooks["note"] = "wall_time_unavailable"
    return hooks


def detect_stuck_locks(
    ledger: Ledger,
    *,
    max_hours: float = DEFAULT_STUCK_LOCK_HOURS,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    rows = ledger._conn.execute(  # noqa: SLF001
        "SELECT lock_id, resource, run_id, acquired_at, state FROM locks WHERE state='open'"
    ).fetchall()
    alerts = []
    for r in rows:
        hours = _hours_ago(r["acquired_at"], now=now)
        if hours is not None and hours >= max_hours:
            alerts.append(
                {
                    "kind": "stuck_lock",
                    "lock_id": r["lock_id"],
                    "resource": r["resource"],
                    "run_id": r["run_id"],
                    "acquired_at": r["acquired_at"],
                    "hours_open": round(hours, 2),
                    "threshold_hours": max_hours,
                }
            )
    return alerts


def detect_missing_receipts(
    ledger: Ledger,
    *,
    max_hours: float = DEFAULT_MISSING_RECEIPT_HOURS,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Jobs in SubmissionUncertain / Submitted without Applied reconcile past N hours."""
    rows = ledger._conn.execute(  # noqa: SLF001
        """
        SELECT job_key, canonical_url, status, updated_at, organization, role
        FROM jobs WHERE status IN ('SubmissionUncertain', 'Submitted', 'Submitting')
        """
    ).fetchall()
    alerts = []
    for r in rows:
        hours = _hours_ago(r["updated_at"], now=now)
        if hours is not None and hours >= max_hours:
            alerts.append(
                {
                    "kind": "missing_receipt",
                    "job_key": r["job_key"],
                    "canonical_url": r["canonical_url"],
                    "status": r["status"],
                    "updated_at": r["updated_at"],
                    "hours_pending": round(hours, 2),
                    "threshold_hours": max_hours,
                    "organization": r["organization"],
                    "role": r["role"],
                }
            )
    return alerts


def worker_timeout_rate(run_dir: Path) -> dict[str, Any]:
    timeouts = 0
    workers = 0
    for path in sorted(run_dir.glob("worker-*.rc")):
        workers += 1
        try:
            rc = int(path.read_text(encoding="utf-8").strip() or "0")
        except ValueError:
            rc = 1
        log = run_dir / f"agent-worker-{path.stem.replace('worker-', '')}.log"
        timed_out = False
        if log.is_file() and "TIMEOUT" in log.read_text(encoding="utf-8", errors="replace"):
            timed_out = True
        if timed_out or rc in {124, 143}:
            timeouts += 1
    rate = (timeouts / workers) if workers else 0.0
    return {
        "workers": workers,
        "timeouts": timeouts,
        "rate": round(rate, 3),
        "alert": rate >= 0.5 and workers > 0,
    }


def build_metrics(
    *,
    run_id: str,
    run_dir: Path,
    eligible_count: int = 0,
    verify_summary: Optional[Mapping[str, Any]] = None,
    run_context: Optional[Mapping[str, Any]] = None,
    submits_today: int = 0,
    ledger: Optional[Ledger] = None,
) -> dict[str, Any]:
    cap_remaining = daily_submit_remaining(submits_today, cap=DAILY_SUBMIT_CAP)
    metrics = {
        "run_id": run_id,
        "eligible_count": eligible_count,
        "verify": collect_verify_stats(verify_summary),
        "wall_time": collect_wall_time(run_dir, run_context),
        "stubbed_workers": collect_stubbed_workers(run_dir),
        "cap_remaining": cap_remaining,
        "daily_submit_cap": DAILY_SUBMIT_CAP,
        "submits_today": submits_today,
        "policy_version": POLICY_VERSION,
        "producer": PRODUCER,
        "created_at": utc_now_iso(),
    }
    return metrics


def build_reliability_alerts(
    *,
    run_dir: Path,
    ledger: Optional[Ledger] = None,
    stuck_lock_hours: float = DEFAULT_STUCK_LOCK_HOURS,
    missing_receipt_hours: float = DEFAULT_MISSING_RECEIPT_HOURS,
) -> dict[str, Any]:
    alerts: list[dict[str, Any]] = []
    if ledger is not None:
        alerts.extend(detect_stuck_locks(ledger, max_hours=stuck_lock_hours))
        alerts.extend(detect_missing_receipts(ledger, max_hours=missing_receipt_hours))
    wt = worker_timeout_rate(run_dir)
    if wt.get("alert"):
        alerts.append({"kind": "worker_timeout_rate", **wt})
    return {
        "ok": True,
        "alert_count": len(alerts),
        "alerts": alerts,
        "worker_timeout": wt,
        "created_at": utc_now_iso(),
        "policy_version": POLICY_VERSION,
    }


def enrich_report_markdown(
    report_text: str,
    *,
    metrics: Mapping[str, Any],
    alerts: Optional[Mapping[str, Any]] = None,
) -> str:
    """Append a Phase 4 metrics section if not already present."""
    marker = "## Phase 4 metrics (R03/R04)"
    if marker in report_text:
        return report_text
    lines = [
        "",
        marker,
        "",
        f"- eligible_count: **{metrics.get('eligible_count', 0)}**",
        f"- cap remaining: **{metrics.get('cap_remaining', 0)}** / {metrics.get('daily_submit_cap', 1)}",
    ]
    verify = metrics.get("verify") or {}
    if verify.get("present"):
        lines.append(
            f"- verify: Eligible={verify.get('eligible', 0)}, "
            f"Needs review={verify.get('needs_review', 0)}, "
            f"Skipped={verify.get('skipped', 0)}, "
            f"Duplicate={verify.get('duplicate', 0)}"
        )
    stubs = metrics.get("stubbed_workers") or []
    if stubs:
        names = ", ".join(s.get("shard_id", "?") for s in stubs)
        lines.append(f"- stubbed workers: {names}")
    else:
        lines.append("- stubbed workers: none")
    wall = metrics.get("wall_time") or {}
    if wall.get("present"):
        if "elapsed_sec" in wall:
            lines.append(f"- wall time: ~{wall['elapsed_sec']}s ({wall.get('source')})")
        elif "elapsed_ms" in wall:
            lines.append(f"- wall time: {wall['elapsed_ms']}ms ({wall.get('source')})")
    else:
        lines.append("- wall time: unavailable (hook ready)")
    if alerts and alerts.get("alert_count"):
        lines.append(f"- reliability alerts: **{alerts['alert_count']}** (see alerts JSON)")
        for a in (alerts.get("alerts") or [])[:5]:
            lines.append(f"  - {a.get('kind')}: {a.get('resource') or a.get('job_key') or a}")
    else:
        lines.append("- reliability alerts: none")
    lines.append("")
    return report_text.rstrip() + "\n" + "\n".join(lines) + "\n"


def write_phase4_artifacts(
    *,
    run_id: str,
    run_dir: Path,
    report_path: Optional[Path] = None,
    eligible_count: int = 0,
    verify_path: Optional[Path] = None,
    run_context_path: Optional[Path] = None,
    submits_today: int = 0,
    db: Optional[Path] = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    verify_summary = None
    if verify_path and Path(verify_path).is_file():
        verify_summary = json.loads(Path(verify_path).read_text(encoding="utf-8"))
    run_context = None
    if run_context_path and Path(run_context_path).is_file():
        run_context = json.loads(Path(run_context_path).read_text(encoding="utf-8"))

    led: Optional[Ledger] = None
    if db:
        led = Ledger(db)
    try:
        metrics = build_metrics(
            run_id=run_id,
            run_dir=run_dir,
            eligible_count=eligible_count,
            verify_summary=verify_summary,
            run_context=run_context,
            submits_today=submits_today,
            ledger=led,
        )
        alerts = build_reliability_alerts(run_dir=run_dir, ledger=led)
        metrics_path = run_dir / "run-metrics.json"
        alerts_path = run_dir / "reliability-alerts.json"
        metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        alerts_path.write_text(json.dumps(alerts, indent=2) + "\n", encoding="utf-8")

        if report_path and Path(report_path).is_file():
            text = Path(report_path).read_text(encoding="utf-8")
            enriched = enrich_report_markdown(text, metrics=metrics, alerts=alerts)
            Path(report_path).write_text(enriched, encoding="utf-8")
            # Also copy into run dir if writing root report
            (run_dir / "last-run-report.md").write_text(enriched, encoding="utf-8")

        return {
            "ok": True,
            "metrics_path": str(metrics_path),
            "alerts_path": str(alerts_path),
            "eligible_count": eligible_count,
            "alert_count": alerts["alert_count"],
            "cap_remaining": metrics["cap_remaining"],
        }
    finally:
        if led is not None:
            led.close()


def _cli() -> int:
    ap = argparse.ArgumentParser(description="R03/R04 run report enrichment")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--report", default="")
    ap.add_argument("--eligible-count", type=int, default=0)
    ap.add_argument("--verify", default="")
    ap.add_argument("--run-context", default="")
    ap.add_argument("--submits-today", type=int, default=0)
    ap.add_argument("--db", default="")
    args = ap.parse_args()
    summary = write_phase4_artifacts(
        run_id=args.run_id,
        run_dir=Path(args.run_dir),
        report_path=Path(args.report) if args.report else None,
        eligible_count=args.eligible_count,
        verify_path=Path(args.verify) if args.verify else None,
        run_context_path=Path(args.run_context) if args.run_context else None,
        submits_today=args.submits_today,
        db=Path(args.db) if args.db else None,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
