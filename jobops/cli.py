#!/usr/bin/env python3
"""Portable jobops CLI — init / doctor / report / run (USER-GUIDE.md)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from agent_runtime import detect_all, select_runtime  # noqa: E402
from user_workspace import (  # noqa: E402
    DEFAULT_CONSENT,
    DEFAULT_PREFERENCES,
    ensure_workspace,
    load_candidate_profile,
    workspace_status,
    write_candidate_profile,
)


def _repo_root() -> Path:
    return ROOT


def cmd_init(args: argparse.Namespace) -> int:
    """
    Create private workspace + candidate profile.

    Never installs control-plane privilege or authority credentials. Operators
    must run ``jobops control-plane provision`` separately after explicit approval.
    """
    paths = ensure_workspace(Path(args.workspace) if args.workspace else None)
    existing = paths["profile"]
    if existing.is_file() and not args.force:
        print(json.dumps({"ok": True, "already_initialized": True, "home": str(paths["home"])}, indent=2))
        return 0

    display = args.name or "Candidate"
    markers = [p.lower() for p in display.split() if p.strip()]
    facts: list[str] = []
    if args.facts_file:
        text = Path(args.facts_file).read_text(encoding="utf-8", errors="replace")
        facts = [ln.strip("-* ").strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not facts:
        facts = [
            "Verified facts not yet imported — add resume facts via jobops init --facts-file.",
            "Do not invent credentials, languages, or work authorization.",
        ]
    resume_urls = [u for u in (args.resume_url or "").split(",") if u.startswith("http")]
    prefs = dict(DEFAULT_PREFERENCES)
    if args.countries:
        prefs["country_priority"] = [c.strip() for c in args.countries.split(",") if c.strip()]
    profile = {
        "display_name": display,
        "identity_markers": markers,
        "resume_urls": resume_urls,
        "verified_facts": facts[:100],
        "preferences": prefs,
        "portal_accounts": {},
        "consent": dict(DEFAULT_CONSENT),
    }
    path = write_candidate_profile(profile, home=paths["home"])
    facts_md = paths["facts"]
    if not facts_md.is_file():
        facts_md.write_text(
            "# Verified facts\n\n" + "\n".join(f"- {f}" for f in facts) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "ok": True,
                "home": str(paths["home"]),
                "profile": str(path),
                "db": str(paths["db"]),
                "isolation_ok": str(paths["home"].resolve()) != str(ROOT.resolve()),
                "next": ["jobops doctor", "jobops run --workflow discovery --dry-run"],
            },
            indent=2,
        )
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    home = Path(args.workspace) if args.workspace else None
    status = workspace_status(home)
    runtimes = [r.to_dict() for r in detect_all()]
    selected = select_runtime(os.environ.get("JOBOPS_RUNTIME")).detect().to_dict()
    checks = {
        "python": sys.version.split()[0],
        "repo_root": str(ROOT),
        "workspace": status,
        "runtime_selected": selected,
        "runtimes": runtimes,
        "submit_default_off": os.environ.get("JOBOPS_ALLOW_SUBMIT", "0") != "1",
        "outreach_send_default_off": os.environ.get("JOBOPS_ENABLE_OUTREACH_SEND", "0") != "1",
        "harness_present": (ROOT / "run").is_file(),
        "contracts_present": (ROOT / "contracts").is_dir(),
    }
    profile = load_candidate_profile(home=home, allow_missing=True)
    blockers = list(profile.missing_reasons)
    if not status["isolation_ok"]:
        blockers.append("workspace_not_isolated_from_repo")
    ok = status["profile_exists"] or bool(profile.verified_facts)
    print(json.dumps({"ok": ok, "blockers": blockers, "checks": checks}, indent=2))
    return 0 if ok and not any(b.startswith("workspace_not") for b in blockers) else 1


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir) if args.run_dir else None
    if run_dir is None:
        runs = ROOT / "runs"
        if runs.is_dir():
            dirs = sorted([p for p in runs.iterdir() if p.is_dir()], reverse=True)
            run_dir = dirs[0] if dirs else None
    if run_dir is None or not run_dir.is_dir():
        print(json.dumps({"ok": False, "error": "no run directory found"}), indent=2)
        return 1
    report = run_dir / "last-run-report.md"
    metrics = run_dir / "run-metrics.json"
    sheets = run_dir / "sheets-sync-plan.json"
    drive = run_dir / "drive-folders.json"
    out: dict[str, Any] = {
        "ok": True,
        "run_dir": str(run_dir),
        "report_exists": report.is_file(),
        "metrics_exists": metrics.is_file(),
    }
    if sheets.is_file():
        plan = json.loads(sheets.read_text(encoding="utf-8"))
        out["sheets"] = {
            "live_api": plan.get("live_api"),
            "integration": plan.get("integration") or "offline_plan",
            "row_count": plan.get("row_count"),
            "reason": plan.get("reason"),
        }
    if drive.is_file():
        d = json.loads(drive.read_text(encoding="utf-8"))
        out["drive"] = {
            "live_api": d.get("live_drive_api", False),
            "integration": "local_mirror" if not d.get("live_drive_api") else "google_drive",
            "count": d.get("count"),
        }
    if args.show_report and report.is_file():
        print(report.read_text(encoding="utf-8"))
    else:
        print(json.dumps(out, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    harness = ROOT / "run"
    if not harness.is_file():
        print(json.dumps({"ok": False, "error": "harness ./run missing"}), indent=2)
        return 2
    env = os.environ.copy()
    env.setdefault("JOBOPS_ALLOW_SUBMIT", "0")
    env.setdefault("JOBOPS_ENABLE_LIVE_SUBMIT", "0")
    env.setdefault("JOBOPS_ENABLE_OUTREACH_SEND", "0")
    env.setdefault("SUBMIT_AGENT", "0")
    env.setdefault("OUTREACH_DRAFTS", "0")
    if args.workspace:
        env["JOBOPS_HOME"] = str(Path(args.workspace).expanduser())
    if args.runtime:
        env["JOBOPS_RUNTIME"] = args.runtime

    # --preview: genuinely non-mutating plan. Does not invoke the harness.
    if getattr(args, "preview", False):
        from agent_runtime import detect_all, select_runtime

        selected = select_runtime(args.runtime or env.get("JOBOPS_RUNTIME")).detect()
        plan = {
            "ok": True,
            "mode": "preview",
            "preview": True,
            "mutating": False,
            "invoked_harness": False,
            "workflow": args.workflow,
            "would_invoke": [str(harness)]
            + (["--pipeline-only"] if args.workflow == "pipeline" or args.pipeline_only else []),
            "gates": {
                "JOBOPS_ALLOW_SUBMIT": "0",
                "JOBOPS_ENABLE_LIVE_SUBMIT": "0",
                "JOBOPS_ENABLE_OUTREACH_SEND": "0",
                "SUBMIT_AGENT": "0",
            },
            "runtime_selected": selected.to_dict(),
            "runtimes_detected": [r.to_dict() for r in detect_all()],
            "preview_semantics": (
                "no harness execution; no ledger/handoff/report writes; "
                "no network fetch/submit/outreach — plan only"
            ),
            "contrast_with_dry_run": (
                "--dry-run still invokes the harness and may write local state; "
                "--preview never mutates"
            ),
        }
        print(json.dumps(plan, indent=2))
        return 0

    cmd = [str(harness)]
    if args.workflow == "pipeline" or args.pipeline_only:
        cmd.append("--pipeline-only")
        if not env.get("PIPELINE_INBOX") and not args.inbox:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "pipeline workflow requires --inbox or PIPELINE_INBOX (no fixture default)",
                    },
                    indent=2,
                )
            )
            return 2
    if args.inbox:
        env["PIPELINE_INBOX"] = str(Path(args.inbox).expanduser())
    if args.dry_run:
        env["SUBMIT_AGENT"] = "0"
        env["JOBOPS_ALLOW_SUBMIT"] = "0"
        env["JOBOPS_ENABLE_LIVE_SUBMIT"] = "0"
        env["JOBOPS_ENABLE_OUTREACH_SEND"] = "0"
        env["JOBOPS_DRY_RUN"] = "1"
    print(
        json.dumps(
            {
                "ok": True,
                "invoking": cmd,
                "workflow": args.workflow,
                "dry_run": bool(args.dry_run),
                "preview": False,
                "dry_run_semantics": (
                    "external_submit_and_outreach_disabled; local_state_may_mutate"
                    if args.dry_run
                    else "full_workflow_subject_to_env_gates"
                ),
                "submit_enabled": env.get("JOBOPS_ALLOW_SUBMIT") == "1"
                and env.get("JOBOPS_ENABLE_LIVE_SUBMIT") == "1",
            },
            indent=2,
        )
    )
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def cmd_control_plane_provision(args: argparse.Namespace) -> int:
    """
    Install OS-gated control-plane credentials (separate from ``jobops approve``).

    Requires ``JOBOPS_CONTROL_PLANE=1`` already set. Never clears ``JOBOPS_AGENT_ROLE``
    — if an agent role is present, provisioning fails closed.
    """
    from authority import (
        AuthorityError,
        bootstrap_control_plane,
        install_control_plane_privilege,
    )
    from trust_boundary import agent_role_from_env, is_untrusted_agent_role
    from user_workspace import default_jobops_home, ensure_workspace

    role = agent_role_from_env()
    if is_untrusted_agent_role(role):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"control_plane_provision_forbidden_in_agent_role:{role}",
                },
                indent=2,
            )
        )
        return 2
    if os.environ.get("JOBOPS_CONTROL_PLANE", "0") != "1":
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "control_plane_not_enabled:"
                    "set JOBOPS_CONTROL_PLANE=1 before provisioning",
                },
                indent=2,
            )
        )
        return 2
    home = Path(args.workspace).expanduser() if args.workspace else default_jobops_home()
    ensure_workspace(home)
    try:
        priv = install_control_plane_privilege(home)
        seal = bootstrap_control_plane(home)
    except AuthorityError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "home": str(home),
                "privilege": str(priv),
                "seal_id": seal.seal_id,
                "note": (
                    "Same-OS-user processes that can open mode-0600 secrets remain "
                    "a residual risk; privilege files are not a TEE/HSM boundary."
                ),
            },
            indent=2,
        )
    )
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """
    Interactive approval: TTY challenge confirm → atomic approve.

    Requires pre-existing control-plane privilege (``jobops control-plane provision``).
    Does not install credentials, does not reset contamination state, and does not
    clear ``JOBOPS_AGENT_ROLE``. Production confirmation is always TTY — synthetic
    echo channels cannot be injected here.
    """
    from approval_controller import ApprovalController, TtyConfirmationChannel
    from authority import AuthorityError, require_privileged_access
    from ledger import Ledger
    from trust_boundary import (
        agent_role_from_env,
        is_untrusted_agent_role,
        open_orchestrator,
    )
    from user_workspace import default_jobops_home

    role = agent_role_from_env()
    if is_untrusted_agent_role(role):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"approve_forbidden_in_agent_role:{role}",
                },
                indent=2,
            )
        )
        return 2
    if os.environ.get("JOBOPS_CONTROL_PLANE", "0") != "1":
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "control_plane_not_enabled:"
                    "set JOBOPS_CONTROL_PLANE=1 and run "
                    "`jobops control-plane provision` first",
                },
                indent=2,
            )
        )
        return 2

    home = Path(args.workspace).expanduser() if args.workspace else default_jobops_home()
    try:
        require_privileged_access(home)
    except AuthorityError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"control_plane_privilege_required:{exc}",
                    "hint": "run `jobops control-plane provision` first",
                },
                indent=2,
            )
        )
        return 2

    db = home / "state" / "jobops.db"
    led = Ledger(db)
    try:
        with open_orchestrator(home, principal=args.principal):
            ctl = ApprovalController(led, workspace_home=home)
            decided = ctl.interactive_approve(
                approval_id=args.approval_id,
                principal=args.principal,
                expected_job_key=args.job_key,
                expected_session_id=args.session_id,
                expected_fingerprint=args.fingerprint,
                channel=TtyConfirmationChannel(),
                workspace_home=home,
            )
        print(
            json.dumps(
                {
                    "ok": True,
                    "approval_id": decided["approval_id"],
                    "status": decided["status"],
                    "decided_by": decided["decided_by"],
                },
                indent=2,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    finally:
        led.close()


def cmd_discover_live(args: argparse.Namespace) -> int:
    """Public ATS GET-only discovery; no submit or outreach paths."""
    from live_discovery import main as discover_main

    argv = ["--sources", args.sources, "--output", args.output,
            "--max-jobs", str(args.max_jobs), "--delay", str(args.delay)]
    if args.ledger:
        argv.extend(["--ledger", args.ledger])
    return discover_main(argv)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jobops", description="jobsOps portable CLI")
    sub = ap.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create private workspace + candidate profile")
    p_init.add_argument("--workspace", default="")
    p_init.add_argument("--name", default="")
    p_init.add_argument("--resume-url", default="")
    p_init.add_argument("--facts-file", default="")
    p_init.add_argument("--countries", default="")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_cp = sub.add_parser(
        "control-plane",
        help="Control-plane credential provisioning (separate from approve)",
    )
    cp_sub = p_cp.add_subparsers(dest="control_plane_command", required=True)
    p_prov = cp_sub.add_parser(
        "provision",
        help="Install OS-gated privilege + authority/confirmation keys",
    )
    p_prov.add_argument("--workspace", default="")
    p_prov.set_defaults(func=cmd_control_plane_provision)

    p_appr = sub.add_parser(
        "approve",
        help=(
            "Interactively confirm and approve a pending approval "
            "(TTY required; privilege must already be provisioned)"
        ),
    )
    p_appr.add_argument("--approval-id", required=True)
    p_appr.add_argument("--principal", required=True)
    p_appr.add_argument("--job-key", required=True)
    p_appr.add_argument("--session-id", required=True)
    p_appr.add_argument("--fingerprint", required=True)
    p_appr.add_argument("--workspace", default="")
    p_appr.set_defaults(func=cmd_approve)

    p_live = sub.add_parser(
        "discover-live",
        help="Read-only discovery from explicitly configured Greenhouse/Lever public API boards",
    )
    p_live.add_argument("--sources", required=True, help="Private JSON registry of approved ATS boards")
    p_live.add_argument("--output", required=True, help="Local JSON evidence report")
    p_live.add_argument("--ledger", default="", help="Optional private SQLite dedupe ledger")
    p_live.add_argument("--max-jobs", type=int, default=250)
    p_live.add_argument("--delay", type=float, default=0.5)
    p_live.set_defaults(func=cmd_discover_live)

    p_doc = sub.add_parser("doctor", help="Check workspace, runtimes, and defaults")
    p_doc.add_argument("--workspace", default="")
    p_doc.set_defaults(func=cmd_doctor)

    p_rep = sub.add_parser("report", help="Summarize latest run artifacts")
    p_rep.add_argument("--run-dir", default="")
    p_rep.add_argument("--show-report", action="store_true")
    p_rep.set_defaults(func=cmd_report)

    p_run = sub.add_parser("run", help="Invoke the local harness")
    p_run.add_argument(
        "--workflow",
        default="daily-search",
        choices=["discovery", "daily-search", "pipeline", "applications", "inbox-reconcile"],
    )
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Disable external submit/outreach (JOBOPS_ALLOW_SUBMIT=0, "
            "JOBOPS_ENABLE_LIVE_SUBMIT=0, SUBMIT_AGENT=0). "
            "Local ledger/handoff/report artifacts may still be written — "
            "not a fully non-mutating rehearsal. Prefer --preview for zero mutation."
        ),
    )
    p_run.add_argument(
        "--preview",
        action="store_true",
        help=(
            "Genuinely non-mutating plan mode: print what would run (workflow, "
            "gates, runtime) without invoking the harness or writing ledger/handoff/report."
        ),
    )
    p_run.add_argument("--pipeline-only", action="store_true")
    p_run.add_argument("--inbox", default="")
    p_run.add_argument("--workspace", default="")
    p_run.add_argument("--runtime", default="")
    p_run.set_defaults(func=cmd_run)

    return ap


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
