#!/usr/bin/env python3
"""F08 Learning (L01–L04) — proposal-only; NEVER mutates lib/policy.py."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import (  # noqa: E402
    POLICY_VERSION,
    make_envelope,
    new_id,
    utc_now_iso,
    validate,
)
from ledger import Ledger  # noqa: E402

PRODUCER = "learning_proposals"
ARTIFACT_LEARNING = "learning_event"
ARTIFACT_EXPERIMENT = "experiment_proposal"

# SOP: do not claim version lift before N matured apps per lane×country.
N_THRESHOLD_DEFAULT = 20

# Absolute hard rule — this module must never write policy.py.
POLICY_PATH = Path(__file__).resolve().parent / "policy.py"


class LearningSafetyError(RuntimeError):
    """Raised if anything attempts to mutate policy without approval."""


def assert_no_policy_mutation() -> None:
    """Guard used by E10: learning path must not open policy.py for write."""
    # Read-only check that the file exists; callers must never write it.
    if not POLICY_PATH.is_file():
        raise LearningSafetyError("policy.py missing — refusing learning run")


def matured_apps_count(jobs: Sequence[Mapping[str, Any]], *, lane_country: str = "") -> int:
    """Count matured applications (Applied / Rejected / Closed with prior Applied signal)."""
    matured_statuses = {"Applied", "Rejected", "Closed", "Follow-up due"}
    n = 0
    for j in jobs:
        status = str(j.get("status") or "")
        if status not in matured_statuses:
            continue
        if lane_country:
            lc = f"{j.get('lane')}|{j.get('country')}"
            if lc != lane_country and str(j.get("country") or "") != lane_country:
                continue
        n += 1
    return n


def outcome_analyst(
    jobs: Sequence[Mapping[str, Any]],
    *,
    lane_country: str = "all",
    n_threshold: int = N_THRESHOLD_DEFAULT,
) -> dict[str, Any]:
    """L01 — Outcome analyst on matured apps (proposal-only)."""
    matured = matured_apps_count(jobs, lane_country="" if lane_country == "all" else lane_country)
    threshold_met = matured >= n_threshold
    findings = [
        f"matured_apps={matured}",
        f"n_threshold={n_threshold}",
        "threshold_met" if threshold_met else "below_threshold_no_version_claim",
    ]
    if not threshold_met:
        findings.append(
            f"Do not claim resume-version lift until {n_threshold} matured apps per lane×country."
        )
    event = {
        "learning_id": new_id("learn_"),
        "kind": "outcome_analyst",
        "summary": (
            f"L01 outcome analysis for {lane_country}: {matured}/{n_threshold} matured apps"
        ),
        "matured_apps": matured,
        "lane_country": lane_country,
        "n_threshold": n_threshold,
        "threshold_met": threshold_met,
        "findings": findings,
        "blockers": [] if threshold_met else ["insufficient_matured_apps"],
        "proposal_only": True,
        "mutates_policy": False,
        "approval_required": True,
        "evidence_refs": [f"ledger:jobs:matured:{matured}"],
        "policy_version": POLICY_VERSION,
        "notes": "Proposal only — never auto-writes eligibility thresholds.",
    }
    validate(event, "learning-event.schema.json")
    return event


def pattern_gap_analyst(
    jobs: Sequence[Mapping[str, Any]],
    *,
    lane_country: str = "all",
) -> dict[str, Any]:
    """L02 — Pattern/gap analyst → structured blockers."""
    status_counts: dict[str, int] = {}
    for j in jobs:
        s = str(j.get("status") or "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
    blockers = []
    if status_counts.get("Needs review", 0) > status_counts.get("Eligible", 0):
        blockers.append("sponsorship_evidence_gap")
    if status_counts.get("Skipped", 0) > 0:
        blockers.append("hard_miss_skips_present")
    if status_counts.get("SubmissionUncertain", 0) > 0:
        blockers.append("uncertain_submits_awaiting_reconcile")
    matured = matured_apps_count(jobs)
    event = {
        "learning_id": new_id("learn_"),
        "kind": "pattern_gap",
        "summary": f"L02 pattern/gap for {lane_country}: {len(blockers)} blocker class(es)",
        "matured_apps": matured,
        "lane_country": lane_country,
        "n_threshold": N_THRESHOLD_DEFAULT,
        "threshold_met": matured >= N_THRESHOLD_DEFAULT,
        "findings": [f"{k}={v}" for k, v in sorted(status_counts.items())],
        "blockers": blockers or ["no_dominant_blocker"],
        "proposal_only": True,
        "mutates_policy": False,
        "approval_required": True,
        "evidence_refs": ["ledger:jobs:status_mix"],
        "policy_version": POLICY_VERSION,
        "notes": "Structured blockers only — no policy mutation.",
    }
    validate(event, "learning-event.schema.json")
    return event


def experiment_designer(
    *,
    lane_country: str = "all",
    matured_apps: int = 0,
    hypothesis: str = "",
) -> dict[str, Any]:
    """L03 — Experiment designer → comparable A/B proposals (approval required)."""
    proposal = {
        "proposal_id": new_id("exp_"),
        "title": f"A/B materials tone — {lane_country}",
        "hypothesis": hypothesis
        or (
            "A concise verified-facts cover note increases interview rate vs baseline "
            "without inventing skills."
        ),
        "variants": [
            {"name": "A_baseline", "description": "Current materials template"},
            {
                "name": "B_concise_verified",
                "description": "Shorter cover emphasizing verified RAG/agentic/TS only",
            },
        ],
        "success_metric": "interviews_per_matured_application",
        "rollback_conditions": [
            "interview_rate_drops_below_baseline",
            "any_invented_skill_detected",
            "user_rejects_proposal",
        ],
        "lane_country": lane_country,
        "matured_apps": matured_apps,
        "proposal_only": True,
        "mutates_policy": False,
        "approval_required": True,
        "approval_status": "pending",
        "evidence_refs": [f"learning:l03:{lane_country}"],
        "policy_version": POLICY_VERSION,
        "notes": "Comparable A/B only after approval; never auto-applies.",
    }
    validate(proposal, "experiment-proposal.schema.json")
    return proposal


def policy_proposal(
    *,
    lane_country: str = "all",
    matured_apps: int = 0,
    change_summary: str = "",
) -> dict[str, Any]:
    """L04 — Policy proposal → approval request + rollback conditions. Does NOT write policy.py."""
    assert_no_policy_mutation()
    event = {
        "learning_id": new_id("learn_"),
        "kind": "policy_proposal",
        "summary": change_summary
        or (
            "Propose raising discovery floor documentation clarity only — "
            "no threshold auto-write."
        ),
        "matured_apps": matured_apps,
        "lane_country": lane_country,
        "n_threshold": N_THRESHOLD_DEFAULT,
        "threshold_met": matured_apps >= N_THRESHOLD_DEFAULT,
        "findings": [
            "policy_change_requires_human_approval",
            "rollback_plan_required",
            "lib/policy.py must remain untouched until approved",
        ],
        "blockers": [] if matured_apps >= N_THRESHOLD_DEFAULT else ["insufficient_matured_apps"],
        "proposal_only": True,
        "mutates_policy": False,
        "approval_required": True,
        "evidence_refs": ["learning:l04:policy_proposal"],
        "policy_version": POLICY_VERSION,
        "notes": "Approval request only. Rollback: revert approval row; keep policy.py unchanged.",
    }
    validate(event, "learning-event.schema.json")
    return event


def apply_policy_mutation_forbidden(
    proposal: Mapping[str, Any],
    *,
    approved: bool = False,
) -> None:
    """
    E10 safety: even with a proposal artifact, never mutate policy.py.
    Approved=True still refuses auto-write (human must edit policy manually).
    """
    assert_no_policy_mutation()
    if proposal.get("mutates_policy") is True:
        raise LearningSafetyError("proposal claims mutates_policy=true — rejected")
    if not proposal.get("proposal_only", True):
        raise LearningSafetyError("non-proposal learning artifact refused")
    if approved:
        # Still do not write — document that human edit is required.
        raise LearningSafetyError(
            "approved proposals still require manual policy.py edit; auto-write forbidden"
        )
    raise LearningSafetyError("policy mutation without approval fixture — blocked")


def generate_weekly_batch(
    jobs: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    lane_country: str = "all",
    ledger: Optional[Ledger] = None,
    write_ledger: bool = True,
) -> dict[str, Any]:
    """Run L01–L04 as a weekly batch; write LearningEvent/ExperimentProposal artifacts only."""
    assert_no_policy_mutation()
    matured = matured_apps_count(jobs)
    l01 = outcome_analyst(jobs, lane_country=lane_country)
    l02 = pattern_gap_analyst(jobs, lane_country=lane_country)
    l03 = experiment_designer(lane_country=lane_country, matured_apps=matured)
    l04 = policy_proposal(lane_country=lane_country, matured_apps=matured)

    written = 0
    if ledger is not None and write_ledger:
        for art_type, payload in (
            (ARTIFACT_LEARNING, l01),
            (ARTIFACT_LEARNING, l02),
            (ARTIFACT_EXPERIMENT, l03),
            (ARTIFACT_LEARNING, l04),
        ):
            env = make_envelope(
                run_id=run_id,
                producer=PRODUCER,
                artifact_type=art_type,
                payload=payload,
                job_key=None,
                task_id=f"{run_id}:learning:{payload.get('learning_id') or payload.get('proposal_id')}",
                evidence_refs=payload.get("evidence_refs") or [],
                status="proposal",
            )
            if ledger.append_artifact(env):
                written += 1

    return {
        "ok": True,
        "run_id": run_id,
        "proposal_only": True,
        "mutates_policy": False,
        "policy_path_untouched": True,
        "policy_path": str(POLICY_PATH),
        "written": written,
        "l01": l01,
        "l02": l02,
        "l03": l03,
        "l04": l04,
        "created_at": utc_now_iso(),
        "policy_version": POLICY_VERSION,
    }


def _cli() -> int:
    ap = argparse.ArgumentParser(description="F08 Learning proposals (never mutates policy)")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--db", default="")
    ap.add_argument("--jobs-json", default="")
    ap.add_argument("--lane-country", default="all")
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    jobs: list[dict[str, Any]] = []
    led: Optional[Ledger] = None
    if args.jobs_json:
        raw = json.loads(Path(args.jobs_json).read_text(encoding="utf-8"))
        jobs = list(raw if isinstance(raw, list) else raw.get("jobs") or [])
    if args.db:
        led = Ledger(args.db)
        if not jobs:
            rows = led._conn.execute(  # noqa: SLF001
                "SELECT job_key, status, country, lane, organization, role FROM jobs"
            ).fetchall()
            jobs = [dict(r) for r in rows]

    try:
        batch = generate_weekly_batch(
            jobs,
            run_id=args.run_id,
            lane_country=args.lane_country,
            ledger=led,
            write_ledger=led is not None and not args.dry_run,
        )
        if args.out:
            Path(args.out).write_text(json.dumps(batch, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: batch[k] for k in batch if k not in {"l01", "l02", "l03", "l04"}}, indent=2))
        print(json.dumps({"l01_id": batch["l01"]["learning_id"], "l03_id": batch["l03"]["proposal_id"]}))
        return 0
    finally:
        if led is not None:
            led.close()


if __name__ == "__main__":
    raise SystemExit(_cli())
