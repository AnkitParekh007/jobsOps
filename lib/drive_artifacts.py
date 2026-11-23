#!/usr/bin/env python3
"""F10 R02 — Drive Artifact Manager: ensure org/role folder paths by job_key (offline)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import POLICY_VERSION, utc_now_iso  # noqa: E402

PRODUCER = "drive_artifacts"
ARCHIVE_FOLDER = "_Screened out - closed or previously applied"


def slugify(text: str, *, fallback: str = "unknown") -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or fallback


def org_folder_name(organization: str) -> str:
    return slugify(organization, fallback="unknown-org")


def role_folder_name(role: str, *, job_key: str = "") -> str:
    base = slugify(role, fallback="role")
    # Disambiguate colliding titles with a short job_key suffix.
    if job_key:
        suffix = slugify(job_key.replace("url:", "").split("/")[-1][:24], fallback="")
        if suffix and suffix not in base:
            return f"{base}--{suffix}"
    return base


def ensure_folder_paths(
    *,
    job_key: str,
    organization: str,
    role: str,
    root: Path,
    archive: bool = False,
) -> dict[str, Any]:
    """
    Ensure local mirror of Drive org/role folders for a job_key.
    Does not call Google Drive API — writes a path map for later sync.
    """
    root = Path(root)
    if archive:
        org_dir = root / ARCHIVE_FOLDER / org_folder_name(organization)
    else:
        org_dir = root / org_folder_name(organization)
    role_dir = org_dir / role_folder_name(role, job_key=job_key)
    role_dir.mkdir(parents=True, exist_ok=True)
    # Marker so empty folders are tracked in git-less local state.
    marker = role_dir / ".jobops-folder.json"
    meta = {
        "job_key": job_key,
        "organization": organization,
        "role": role,
        "org_folder": str(org_dir.relative_to(root)),
        "role_folder": str(role_dir.relative_to(root)),
        "absolute_role_folder": str(role_dir),
        "archive": archive,
        "created_at": utc_now_iso(),
        "policy_version": POLICY_VERSION,
        "producer": PRODUCER,
        "live_drive_api": False,
    }
    marker.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def ensure_from_job(job: Mapping[str, Any], *, root: Path, archive: bool = False) -> dict[str, Any]:
    status = str(job.get("status") or "").lower()
    use_archive = archive or status in {"skipped", "closed", "rejected", "duplicate"}
    return ensure_folder_paths(
        job_key=str(job.get("job_key") or ""),
        organization=str(job.get("organization") or "unknown"),
        role=str(job.get("role") or "role"),
        root=root,
        archive=use_archive,
    )


def ensure_batch(
    jobs: list[Mapping[str, Any]],
    *,
    root: Path,
) -> dict[str, Any]:
    results = []
    for job in jobs:
        if not job.get("job_key"):
            continue
        results.append(ensure_from_job(job, root=root))
    return {
        "ok": True,
        "root": str(root),
        "folders": results,
        "count": len(results),
        "live_drive_api": False,
        "policy_version": POLICY_VERSION,
    }


def _cli() -> int:
    ap = argparse.ArgumentParser(description="R02 Drive folder path helpers (offline)")
    ap.add_argument("--root", required=True, help="Local Drive mirror root")
    ap.add_argument("--job-key", default="")
    ap.add_argument("--organization", default="")
    ap.add_argument("--role", default="")
    ap.add_argument("--jobs-json", default="", help="JSON list of jobs")
    ap.add_argument("--out", default="")
    ap.add_argument("--archive", action="store_true")
    args = ap.parse_args()

    if args.jobs_json:
        jobs = json.loads(Path(args.jobs_json).read_text(encoding="utf-8"))
        if isinstance(jobs, dict):
            jobs = jobs.get("jobs") or []
        summary = ensure_batch(list(jobs), root=Path(args.root))
    else:
        if not args.job_key:
            print(json.dumps({"ok": False, "error": "job-key or jobs-json required"}))
            return 2
        meta = ensure_folder_paths(
            job_key=args.job_key,
            organization=args.organization or "unknown",
            role=args.role or "role",
            root=Path(args.root),
            archive=args.archive,
        )
        summary = {"ok": True, "folders": [meta], "count": 1, "live_drive_api": False}

    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
