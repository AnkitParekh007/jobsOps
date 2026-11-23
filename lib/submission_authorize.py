#!/usr/bin/env python3
"""F05/F09 submission authorize gate — deterministic; never auto-retry after uncertain."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from contracts import (  # noqa: E402
    POLICY_VERSION,
    ContractError,
    job_key_from_url,
    make_envelope,
    normalize_url,
    validate,
)
from ledger import Ledger  # noqa: E402
from policy import (  # noqa: E402
    DAILY_SUBMIT_CAP,
    check_daily_submit_cap,
    check_verified_fact_claim,
    daily_submit_remaining,
    post_submit_timeout_hold,
    tool_allowed,
)

PRODUCER = "submission_authorize"
ARTIFACT_TYPE_PACKAGE = "application_package"
ARTIFACT_TYPE_RECEIPT = "submission_receipt"

ATS_FLOOR = 80
QUALITY_FLOOR = 75

# Application-package states (Phase 3).
STATE_PREPARING = "Preparing"
STATE_MATERIALS_VALIDATED = "MaterialsValidated"
STATE_READY_FOR_APPROVAL = "ReadyForApproval"
STATE_SUBMISSION_AUTHORIZED = "SubmissionAuthorized"
STATE_SUBMITTING = "Submitting"
STATE_APPLIED = "Applied"
STATE_UNCERTAIN = "SubmissionUncertain"

SOP_STATUS_MAP = {
    STATE_PREPARING: "In preparation",
    STATE_MATERIALS_VALIDATED: "In preparation",
    STATE_READY_FOR_APPROVAL: "Ready for approval",
    STATE_SUBMISSION_AUTHORIZED: "Ready for approval",
    STATE_SUBMITTING: "Submitted",
    STATE_APPLIED: "Applied",
    STATE_UNCERTAIN: "On hold",
}

# Checklist items required for SubmissionAuthorized (SOP §14 subset that is deterministic).
REQUIRED_CHECKLIST = (
    "posting_open",
    "not_duplicate",
    "hard_eligibility_met",
    "pdf_validated",
    "fingerprint_matches_scores",
    "ats_gate",
    "quality_gate",
    "filenames_correct",
    "required_fields_complete",
    "screening_answers_verified",
    "no_auth_wall",
    "session_authorized_if_needed",
    "form_lock_held",
    "auto_submit_or_user_approved",
    "daily_cap_allows",
)

# Materials → Ready for approval can pass with a subset (human still confirms).
READY_CHECKLIST = (
    "pdf_validated",
    "fingerprint_matches_scores",
    "ats_gate",
    "quality_gate",
    "filenames_correct",
    "hard_eligibility_met",
)


@dataclass
class AuthorizeResult:
    authorized: bool
    state: str
    sop_status: str
    package: dict[str, Any]
    blocking_reasons: list[str] = field(default_factory=list)
    code: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "state": self.state,
            "sop_status": self.sop_status,
            "blocking_reasons": self.blocking_reasons,
            "code": self.code,
            "message": self.message,
            "package": self.package,
            "policy_version": POLICY_VERSION,
        }


def fingerprint_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint_text(text: str) -> str:
    normalized = " ".join((text or "").split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def fingerprint_pdf_file(path: Path) -> tuple[str, str]:
    """Return (fingerprint, method). Prefer byte SHA-256 of PDF."""
    raw = path.read_bytes()
    return fingerprint_bytes(raw), "sha256_bytes"


def extract_pdf_text(path: Path) -> str:
    """
    Best-effort PDF text extract for E07.
    Uses pypdf if available; otherwise returns empty (caller may supply extracted_text).
    """
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            return ""
    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
    except Exception:  # noqa: BLE001
        return ""


def default_checklist(**overrides: bool) -> dict[str, bool]:
    base = {k: False for k in REQUIRED_CHECKLIST}
    base.update(overrides)
    return base


def count_submits_today(ledger: Optional[Ledger], *, today: Optional[str] = None) -> int:
    """
    Count Applied/Submitted artifacts for Asia/Kolkata calendar date.
    `today` override is ISO date YYYY-MM-DD for fixtures.
    """
    if ledger is None:
        return 0
    if today is None:
        today = datetime_today_kolkata()
    rows = ledger._conn.execute(  # noqa: SLF001
        """
        SELECT status, updated_at, meta_json FROM jobs
        WHERE status IN ('Applied', 'Submitted')
        """
    ).fetchall()
    n = 0
    for r in rows:
        updated = (r["updated_at"] or "")[:10]
        # Prefer meta submit_date if present
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        submit_date = str(meta.get("submit_date") or updated)
        if submit_date.startswith(today):
            n += 1
    # Also count submission_receipt Applied outcomes today
    arts = ledger._conn.execute(  # noqa: SLF001
        """
        SELECT created_at, payload_json FROM artifacts
        WHERE artifact_type=? AND status IN ('Applied', 'Submitted', 'ok')
        """,
        (ARTIFACT_TYPE_RECEIPT,),
    ).fetchall()
    for a in arts:
        try:
            payload = json.loads(a["payload_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if payload.get("outcome") not in {"Applied", "Submitted"}:
            continue
        created = (a["created_at"] or "")[:10]
        if created.startswith(today) or str(payload.get("submit_date") or "").startswith(today):
            n += 1
    return n


def datetime_today_kolkata() -> str:
    from datetime import datetime

    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    except Exception:  # noqa: BLE001
        return datetime.utcnow().date().isoformat()


def form_lock_resource(canonical_url: str) -> str:
    return f"form:{normalize_url(canonical_url)}"


def check_form_lock(
    ledger: Optional[Ledger],
    *,
    canonical_url: str,
    run_id: str,
) -> dict[str, Any]:
    resource = form_lock_resource(canonical_url)
    if ledger is None:
        return {
            "held": False,
            "resource": resource,
            "lock_id": None,
            "run_id": None,
            "reason": "no_ledger",
        }
    row = ledger._conn.execute(  # noqa: SLF001
        "SELECT lock_id, run_id, state FROM locks WHERE resource=?",
        (resource,),
    ).fetchone()
    if row and row["state"] == "open" and row["run_id"] == run_id:
        return {
            "held": True,
            "resource": resource,
            "lock_id": row["lock_id"],
            "run_id": row["run_id"],
        }
    if row and row["state"] == "open":
        return {
            "held": False,
            "resource": resource,
            "lock_id": row["lock_id"],
            "run_id": row["run_id"],
            "reason": "lock_held_by_other_run",
        }
    return {
        "held": False,
        "resource": resource,
        "lock_id": None,
        "run_id": None,
        "reason": "lock_not_held",
    }


def acquire_form_lock(ledger: Ledger, *, canonical_url: str, run_id: str) -> str:
    return ledger.acquire_lock(form_lock_resource(canonical_url), run_id)


def validate_materials(
    *,
    extracted_text: str,
    ats_score: float,
    quality_score: float,
    pdf_fingerprint: str,
    ats_score_fingerprint: Optional[str],
    quality_score_fingerprint: Optional[str],
    fingerprint_method: str,
) -> tuple[bool, list[str]]:
    """E07 materials gates: floors, fingerprint match, no invented skills."""
    blocking: list[str] = []
    if not pdf_fingerprint or not str(pdf_fingerprint).strip():
        blocking.append("missing_pdf_fingerprint")
    if fingerprint_method not in {"sha256_bytes", "sha256_normalized_text", "fixture"}:
        blocking.append("invalid_fingerprint_method")
    if ats_score < ATS_FLOOR:
        blocking.append(f"ats_below_floor:{ats_score}<{ATS_FLOOR}")
    if quality_score < QUALITY_FLOOR:
        blocking.append(f"quality_below_floor:{quality_score}<{QUALITY_FLOOR}")

    fp = str(pdf_fingerprint)
    if ats_score_fingerprint and ats_score_fingerprint != fp:
        blocking.append("ats_fingerprint_mismatch")
    if quality_score_fingerprint and quality_score_fingerprint != fp:
        blocking.append("quality_fingerprint_mismatch")
    # If score fingerprints omitted, treat as mismatch for authorize (stale risk).
    if not ats_score_fingerprint:
        blocking.append("ats_score_fingerprint_missing")
    if not quality_score_fingerprint:
        blocking.append("quality_score_fingerprint_missing")

    claim = check_verified_fact_claim(extracted_text or "")
    if not claim.ok:
        blocking.append(f"invented_claim:{claim.blocking_reasons[0] if claim.blocking_reasons else claim.code}")

    # Identity markers in extract (name) — soft fail if completely empty extract
    if not (extracted_text or "").strip():
        blocking.append("empty_pdf_extract")
    else:
        lowered = extracted_text.lower()
        if "ankit" not in lowered or "parekh" not in lowered:
            blocking.append("identity_not_in_pdf_extract")

    return len(blocking) == 0, blocking


def build_application_package(
    *,
    job_key: str,
    canonical_url: str,
    run_id: str,
    state: str,
    ats_score: float,
    quality_score: float,
    pdf_fingerprint: str,
    fingerprint_method: str,
    checklist: Mapping[str, bool],
    blocking_reasons: Sequence[str],
    organization: str = "",
    role: str = "",
    pdf_path: Optional[str] = None,
    ats_score_fingerprint: Optional[str] = None,
    quality_score_fingerprint: Optional[str] = None,
    extracted_text: str = "",
    session_lock: Optional[Mapping[str, Any]] = None,
    daily_cap: Optional[Mapping[str, Any]] = None,
    evidence_package: Optional[Mapping[str, Any]] = None,
    notes: str = "",
    retryable: bool = False,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    pkg = {
        "job_key": job_key,
        "canonical_url": normalize_url(canonical_url),
        "run_id": run_id,
        "organization": organization,
        "role": role,
        "state": state,
        "sop_status": SOP_STATUS_MAP.get(state, "Needs review"),
        "pdf_path": pdf_path,
        "pdf_fingerprint": pdf_fingerprint,
        "fingerprint_method": fingerprint_method,
        "ats_score": float(ats_score),
        "quality_score": float(quality_score),
        "ats_score_fingerprint": ats_score_fingerprint,
        "quality_score_fingerprint": quality_score_fingerprint,
        "extracted_text": extracted_text,
        "checklist": dict(checklist),
        "session_lock": dict(session_lock or {}),
        "daily_cap": dict(daily_cap or {}),
        "evidence_package": dict(evidence_package or {}),
        "blocking_reasons": list(blocking_reasons),
        "retryable": bool(retryable),
        "policy_version": policy_version,
        "notes": notes,
    }
    validate(pkg, "application-package.schema.json")
    return pkg


def authorize_submission(
    package_input: Mapping[str, Any],
    *,
    run_id: str,
    ledger: Optional[Ledger] = None,
    submits_today: Optional[int] = None,
    require_form_lock: bool = True,
    dry_run: bool = False,
    prior_uncertain: bool = False,
    policy_version: str = POLICY_VERSION,
) -> AuthorizeResult:
    """
    Deterministic gate before any browser submit.

    dry_run=True stops at ReadyForApproval when materials pass (no SubmissionAuthorized).
    Never auto-retries after SubmissionUncertain (prior_uncertain → block).
    """
    url = str(package_input.get("canonical_url") or "")
    if not url.startswith("http"):
        raise ContractError("canonical_url required")
    canon = normalize_url(url)
    jk = str(package_input.get("job_key") or job_key_from_url(canon))

    # Hard rule: never retry uncertain without Phase 4 reconcile
    if prior_uncertain or package_input.get("state") == STATE_UNCERTAIN:
        pkg = build_application_package(
            job_key=jk,
            canonical_url=canon,
            run_id=run_id,
            state=STATE_UNCERTAIN,
            ats_score=float(package_input.get("ats_score") or 0),
            quality_score=float(package_input.get("quality_score") or 0),
            pdf_fingerprint=str(package_input.get("pdf_fingerprint") or "none"),
            fingerprint_method=str(package_input.get("fingerprint_method") or "fixture"),
            checklist=package_input.get("checklist") or default_checklist(),
            blocking_reasons=["prior_submission_uncertain_no_auto_retry"],
            organization=str(package_input.get("organization") or ""),
            role=str(package_input.get("role") or ""),
            pdf_path=package_input.get("pdf_path"),
            notes="Never auto-retry after uncertain submit; require Gmail/portal reconcile",
            retryable=False,
            policy_version=policy_version,
        )
        return AuthorizeResult(
            False,
            STATE_UNCERTAIN,
            SOP_STATUS_MAP[STATE_UNCERTAIN],
            pkg,
            blocking_reasons=["prior_submission_uncertain_no_auto_retry"],
            code="no_auto_retry_uncertain",
            message="SubmissionUncertain cannot auto-retry",
        )

    # Role tool gate
    tool = tool_allowed("frontier_submit", "submit")
    if not tool.ok:
        blocking = list(tool.blocking_reasons)
        pkg = build_application_package(
            job_key=jk,
            canonical_url=canon,
            run_id=run_id,
            state=STATE_PREPARING,
            ats_score=float(package_input.get("ats_score") or 0),
            quality_score=float(package_input.get("quality_score") or 0),
            pdf_fingerprint=str(package_input.get("pdf_fingerprint") or "none"),
            fingerprint_method=str(package_input.get("fingerprint_method") or "fixture"),
            checklist=package_input.get("checklist") or default_checklist(),
            blocking_reasons=blocking,
            policy_version=policy_version,
        )
        return AuthorizeResult(
            False, STATE_PREPARING, SOP_STATUS_MAP[STATE_PREPARING], pkg, blocking, tool.code, tool.message
        )

    extracted = str(package_input.get("extracted_text") or "")
    pdf_path = package_input.get("pdf_path")
    fingerprint = str(package_input.get("pdf_fingerprint") or "")
    method = str(package_input.get("fingerprint_method") or "fixture")
    if pdf_path and Path(str(pdf_path)).is_file() and not fingerprint:
        fingerprint, method = fingerprint_pdf_file(Path(str(pdf_path)))
        if not extracted:
            extracted = extract_pdf_text(Path(str(pdf_path)))

    ats = float(package_input.get("ats_score") or 0)
    quality = float(package_input.get("quality_score") or 0)
    ats_fp = package_input.get("ats_score_fingerprint")
    qual_fp = package_input.get("quality_score_fingerprint")
    if isinstance(ats_fp, str):
        ats_fp_s: Optional[str] = ats_fp
    else:
        ats_fp_s = fingerprint or None
    if isinstance(qual_fp, str):
        qual_fp_s: Optional[str] = qual_fp
    else:
        qual_fp_s = fingerprint or None

    materials_ok, mat_blocking = validate_materials(
        extracted_text=extracted,
        ats_score=ats,
        quality_score=quality,
        pdf_fingerprint=fingerprint or "missing",
        ats_score_fingerprint=ats_fp_s,
        quality_score_fingerprint=qual_fp_s,
        fingerprint_method=method,
    )

    checklist = default_checklist(**dict(package_input.get("checklist") or {}))
    # Derive checklist bits from materials
    checklist["ats_gate"] = ats >= ATS_FLOOR
    checklist["quality_gate"] = quality >= QUALITY_FLOOR
    checklist["fingerprint_matches_scores"] = (
        bool(fingerprint)
        and ats_fp_s == fingerprint
        and qual_fp_s == fingerprint
    )
    checklist["pdf_validated"] = materials_ok or checklist.get("pdf_validated", False)
    if materials_ok:
        checklist["pdf_validated"] = True

    # Daily cap
    if submits_today is None:
        submits_today = count_submits_today(ledger)
    cap_verdict = check_daily_submit_cap(submits_today, cap=DAILY_SUBMIT_CAP)
    remaining = daily_submit_remaining(submits_today, cap=DAILY_SUBMIT_CAP)
    checklist["daily_cap_allows"] = cap_verdict.ok
    daily_cap_info = {
        "cap": DAILY_SUBMIT_CAP,
        "submits_today": submits_today,
        "remaining": remaining,
    }

    # Session / form lock
    lock_info = check_form_lock(ledger, canonical_url=canon, run_id=run_id)
    if require_form_lock:
        checklist["form_lock_held"] = bool(lock_info.get("held"))
    else:
        checklist["form_lock_held"] = checklist.get("form_lock_held", False) or bool(
            package_input.get("session_lock", {}).get("held")
        )
        if package_input.get("session_lock"):
            lock_info = dict(package_input["session_lock"])

    evidence = dict(package_input.get("evidence_package") or {})
    evidence.setdefault("ats_floor", ATS_FLOOR)
    evidence.setdefault("quality_floor", QUALITY_FLOOR)
    evidence["materials_ok"] = materials_ok
    evidence["materials_blocking"] = mat_blocking

    blocking: list[str] = []
    if not materials_ok:
        blocking.extend(mat_blocking)

    # --- State machine ---
    if not materials_ok:
        state = STATE_PREPARING
        pkg = build_application_package(
            job_key=jk,
            canonical_url=canon,
            run_id=run_id,
            state=state,
            ats_score=ats,
            quality_score=quality,
            pdf_fingerprint=fingerprint or "missing",
            fingerprint_method=method,
            checklist=checklist,
            blocking_reasons=blocking,
            organization=str(package_input.get("organization") or ""),
            role=str(package_input.get("role") or ""),
            pdf_path=str(pdf_path) if pdf_path else None,
            ats_score_fingerprint=ats_fp_s,
            quality_score_fingerprint=qual_fp_s,
            extracted_text=extracted,
            session_lock=lock_info,
            daily_cap=daily_cap_info,
            evidence_package=evidence,
            notes="materials not validated",
            retryable=True,
            policy_version=policy_version,
        )
        return AuthorizeResult(
            False, state, SOP_STATUS_MAP[state], pkg, blocking, "materials_incomplete", "Preparing"
        )

    # MaterialsValidated
    state = STATE_MATERIALS_VALIDATED

    ready_fail = [k for k in READY_CHECKLIST if not checklist.get(k)]
    if ready_fail:
        blocking.extend([f"checklist:{k}" for k in ready_fail])
        pkg = build_application_package(
            job_key=jk,
            canonical_url=canon,
            run_id=run_id,
            state=STATE_PREPARING,
            ats_score=ats,
            quality_score=quality,
            pdf_fingerprint=fingerprint,
            fingerprint_method=method,
            checklist=checklist,
            blocking_reasons=blocking,
            organization=str(package_input.get("organization") or ""),
            role=str(package_input.get("role") or ""),
            pdf_path=str(pdf_path) if pdf_path else None,
            ats_score_fingerprint=ats_fp_s,
            quality_score_fingerprint=qual_fp_s,
            extracted_text=extracted,
            session_lock=lock_info,
            daily_cap=daily_cap_info,
            evidence_package=evidence,
            notes="ready checklist incomplete",
            retryable=True,
            policy_version=policy_version,
        )
        return AuthorizeResult(
            False,
            STATE_PREPARING,
            SOP_STATUS_MAP[STATE_PREPARING],
            pkg,
            blocking,
            "ready_checklist_incomplete",
            "not ready for approval",
        )

    # Ready for approval — materials + floors pass
    if dry_run or package_input.get("require_human_approval") or not checklist.get(
        "auto_submit_or_user_approved", False
    ):
        # Dry-run / human confirmation path
        extra_block: list[str] = []
        if dry_run:
            extra_block.append("dry_run_ready_for_approval")
        if not checklist.get("auto_submit_or_user_approved", False):
            extra_block.append("human_approval_required")
        pkg = build_application_package(
            job_key=jk,
            canonical_url=canon,
            run_id=run_id,
            state=STATE_READY_FOR_APPROVAL,
            ats_score=ats,
            quality_score=quality,
            pdf_fingerprint=fingerprint,
            fingerprint_method=method,
            checklist=checklist,
            blocking_reasons=extra_block,
            organization=str(package_input.get("organization") or ""),
            role=str(package_input.get("role") or ""),
            pdf_path=str(pdf_path) if pdf_path else None,
            ats_score_fingerprint=ats_fp_s,
            quality_score_fingerprint=qual_fp_s,
            extracted_text=extracted,
            session_lock=lock_info,
            daily_cap=daily_cap_info,
            evidence_package={**evidence, "ready_for_approval": True},
            notes="Ready for approval — full evidence package; no live submit",
            retryable=False,
            policy_version=policy_version,
        )
        return AuthorizeResult(
            False,
            STATE_READY_FOR_APPROVAL,
            SOP_STATUS_MAP[STATE_READY_FOR_APPROVAL],
            pkg,
            extra_block,
            "ready_for_approval",
            "materials validated; awaiting approval / dry-run",
        )

    # Full authorize path
    if not cap_verdict.ok:
        blocking.append("daily_submit_cap")
        pkg = build_application_package(
            job_key=jk,
            canonical_url=canon,
            run_id=run_id,
            state=STATE_READY_FOR_APPROVAL,
            ats_score=ats,
            quality_score=quality,
            pdf_fingerprint=fingerprint,
            fingerprint_method=method,
            checklist=checklist,
            blocking_reasons=blocking,
            organization=str(package_input.get("organization") or ""),
            role=str(package_input.get("role") or ""),
            pdf_path=str(pdf_path) if pdf_path else None,
            ats_score_fingerprint=ats_fp_s,
            quality_score_fingerprint=qual_fp_s,
            extracted_text=extracted,
            session_lock=lock_info,
            daily_cap=daily_cap_info,
            evidence_package=evidence,
            notes="cap reached — stay Ready for approval",
            retryable=False,
            policy_version=policy_version,
        )
        return AuthorizeResult(
            False,
            STATE_READY_FOR_APPROVAL,
            SOP_STATUS_MAP[STATE_READY_FOR_APPROVAL],
            pkg,
            blocking,
            "daily_submit_cap",
            cap_verdict.message,
        )

    if require_form_lock and not checklist.get("form_lock_held"):
        blocking.append("form_lock_not_held")
        pkg = build_application_package(
            job_key=jk,
            canonical_url=canon,
            run_id=run_id,
            state=STATE_MATERIALS_VALIDATED,
            ats_score=ats,
            quality_score=quality,
            pdf_fingerprint=fingerprint,
            fingerprint_method=method,
            checklist=checklist,
            blocking_reasons=blocking,
            organization=str(package_input.get("organization") or ""),
            role=str(package_input.get("role") or ""),
            pdf_path=str(pdf_path) if pdf_path else None,
            ats_score_fingerprint=ats_fp_s,
            quality_score_fingerprint=qual_fp_s,
            extracted_text=extracted,
            session_lock=lock_info,
            daily_cap=daily_cap_info,
            evidence_package=evidence,
            notes="form lock required before submit",
            retryable=True,
            policy_version=policy_version,
        )
        return AuthorizeResult(
            False,
            STATE_MATERIALS_VALIDATED,
            SOP_STATUS_MAP[STATE_MATERIALS_VALIDATED],
            pkg,
            blocking,
            "form_lock_required",
            "hold form lock before SubmissionAuthorized",
        )

    submit_fail = [k for k in REQUIRED_CHECKLIST if not checklist.get(k)]
    if submit_fail:
        blocking.extend([f"checklist:{k}" for k in submit_fail])
        pkg = build_application_package(
            job_key=jk,
            canonical_url=canon,
            run_id=run_id,
            state=STATE_READY_FOR_APPROVAL,
            ats_score=ats,
            quality_score=quality,
            pdf_fingerprint=fingerprint,
            fingerprint_method=method,
            checklist=checklist,
            blocking_reasons=blocking,
            organization=str(package_input.get("organization") or ""),
            role=str(package_input.get("role") or ""),
            pdf_path=str(pdf_path) if pdf_path else None,
            ats_score_fingerprint=ats_fp_s,
            quality_score_fingerprint=qual_fp_s,
            extracted_text=extracted,
            session_lock=lock_info,
            daily_cap=daily_cap_info,
            evidence_package=evidence,
            notes="submit checklist incomplete",
            retryable=True,
            policy_version=policy_version,
        )
        return AuthorizeResult(
            False,
            STATE_READY_FOR_APPROVAL,
            SOP_STATUS_MAP[STATE_READY_FOR_APPROVAL],
            pkg,
            blocking,
            "submit_checklist_incomplete",
            "Ready for approval; checklist incomplete for auto-submit",
        )

    pkg = build_application_package(
        job_key=jk,
        canonical_url=canon,
        run_id=run_id,
        state=STATE_SUBMISSION_AUTHORIZED,
        ats_score=ats,
        quality_score=quality,
        pdf_fingerprint=fingerprint,
        fingerprint_method=method,
        checklist=checklist,
        blocking_reasons=[],
        organization=str(package_input.get("organization") or ""),
        role=str(package_input.get("role") or ""),
        pdf_path=str(pdf_path) if pdf_path else None,
        ats_score_fingerprint=ats_fp_s,
        quality_score_fingerprint=qual_fp_s,
        extracted_text=extracted,
        session_lock=lock_info,
        daily_cap=daily_cap_info,
        evidence_package={**evidence, "authorized": True},
        notes="SubmissionAuthorized — browser submit may proceed once",
        retryable=False,
        policy_version=policy_version,
    )
    return AuthorizeResult(
        True,
        STATE_SUBMISSION_AUTHORIZED,
        SOP_STATUS_MAP[STATE_SUBMISSION_AUTHORIZED],
        pkg,
        [],
        "submission_authorized",
        "all gates passed",
    )


def record_submission_outcome(
    *,
    job_key: str,
    canonical_url: str,
    run_id: str,
    portal_confirmation: bool,
    gmail_receipt: bool,
    confirmation_url: Optional[str] = None,
    gmail_message_id: Optional[str] = None,
    pdf_fingerprint: Optional[str] = None,
    evidence_refs: Optional[Sequence[str]] = None,
    ledger: Optional[Ledger] = None,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    """
    Map post-submit evidence → Applied | Submitted | SubmissionUncertain.
    Uncertain is never retryable and must not be recorded as Applied.
    """
    verdict = post_submit_timeout_hold(
        confirmation_seen=portal_confirmation,
        gmail_receipt=gmail_receipt,
    )
    if verdict.decision == "Applied":
        outcome = STATE_APPLIED
    elif verdict.decision == "Submitted":
        outcome = "Submitted"
    else:
        outcome = STATE_UNCERTAIN

    receipt = {
        "job_key": job_key,
        "canonical_url": normalize_url(canonical_url),
        "run_id": run_id,
        "outcome": outcome,
        "portal_confirmation": bool(portal_confirmation),
        "gmail_receipt": bool(gmail_receipt),
        "confirmation_url": confirmation_url,
        "gmail_message_id": gmail_message_id,
        "evidence_refs": list(evidence_refs or ([confirmation_url] if confirmation_url else [])),
        "pdf_fingerprint": pdf_fingerprint,
        "retryable": False,  # never auto-retry after any terminal submit attempt
        "blocking_reasons": list(verdict.blocking_reasons),
        "policy_version": policy_version,
        "notes": verdict.message,
    }
    validate(receipt, "submission-receipt.schema.json")

    if ledger is not None:
        env = make_envelope(
            run_id=run_id,
            producer=PRODUCER,
            artifact_type=ARTIFACT_TYPE_RECEIPT,
            payload=receipt,
            job_key=job_key,
            task_id=f"{run_id}:submit-receipt",
            status=outcome,
            evidence_refs=receipt["evidence_refs"],
            blocking_reasons=receipt["blocking_reasons"],
            retryable=False,
        )
        ledger.append_artifact(env)
        sop = "Applied" if outcome == STATE_APPLIED else (
            "Submitted" if outcome == "Submitted" else "On hold"
        )
        ledger.transition_job(
            job_key,
            canonical_url=normalize_url(canonical_url),
            status=sop,
            run_id=run_id,
            meta={
                "submission_outcome": outcome,
                "retryable": False,
                "submit_date": datetime_today_kolkata(),
            },
        )
    return receipt


def would_allow_submit(
    *,
    shortlist_count: int,
    submits_today: int = 0,
    cap: int = DAILY_SUBMIT_CAP,
) -> bool:
    """Harness helper: invoke submit agent only if shortlist non-empty and cap remaining."""
    return shortlist_count > 0 and daily_submit_remaining(submits_today, cap=cap) > 0


def _cli() -> int:
    ap = argparse.ArgumentParser(description="JobOps F09 submission_authorize gate")
    ap.add_argument("--package", default="", help="application package JSON input")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--db", default="", help="ledger db")
    ap.add_argument("--out", default="", help="write authorize result JSON")
    ap.add_argument("--dry-run", action="store_true", help="stop at ReadyForApproval")
    ap.add_argument("--acquire-lock", action="store_true", help="acquire form lock first")
    ap.add_argument("--submits-today", type=int, default=-1)
    ap.add_argument("--shortlist", default="", help="ranked-shortlist.json — gate invoke check")
    ap.add_argument("--check-only", action="store_true", help="print would_allow_submit only")
    ap.add_argument("--record-outcome", default="", help="JSON with portal/gmail flags")
    args = ap.parse_args()

    ledger: Optional[Ledger] = Ledger(args.db) if args.db else None

    if args.check_only or (args.shortlist and not args.package):
        shortlist_count = 0
        if args.shortlist and Path(args.shortlist).is_file():
            data = json.loads(Path(args.shortlist).read_text(encoding="utf-8"))
            shortlist_count = len(data.get("shortlist") or [])
        submits = args.submits_today if args.submits_today >= 0 else count_submits_today(ledger)
        allow = would_allow_submit(shortlist_count=shortlist_count, submits_today=submits)
        out = {
            "ok": True,
            "allow_submit_agent": allow,
            "shortlist_count": shortlist_count,
            "submits_today": submits,
            "cap": DAILY_SUBMIT_CAP,
            "remaining": daily_submit_remaining(submits),
        }
        print(json.dumps(out, indent=2))
        if ledger:
            ledger.close()
        return 0 if allow else 1

    if args.record_outcome:
        raw = json.loads(Path(args.record_outcome).read_text(encoding="utf-8"))
        receipt = record_submission_outcome(
            job_key=str(raw["job_key"]),
            canonical_url=str(raw["canonical_url"]),
            run_id=args.run_id,
            portal_confirmation=bool(raw.get("portal_confirmation")),
            gmail_receipt=bool(raw.get("gmail_receipt")),
            confirmation_url=raw.get("confirmation_url"),
            gmail_message_id=raw.get("gmail_message_id"),
            pdf_fingerprint=raw.get("pdf_fingerprint"),
            evidence_refs=raw.get("evidence_refs"),
            ledger=ledger,
        )
        print(json.dumps({"ok": True, "receipt": receipt}, indent=2))
        if ledger:
            ledger.close()
        return 0

    if not args.package:
        print(json.dumps({"ok": False, "error": "--package required"}), file=sys.stderr)
        if ledger:
            ledger.close()
        return 2

    package_input = json.loads(Path(args.package).read_text(encoding="utf-8"))
    if args.acquire_lock and ledger is not None:
        url = package_input.get("canonical_url") or ""
        lid = acquire_form_lock(ledger, canonical_url=str(url), run_id=args.run_id)
        package_input.setdefault("session_lock", {})
        package_input["session_lock"] = {
            "held": True,
            "resource": form_lock_resource(str(url)),
            "lock_id": lid,
            "run_id": args.run_id,
        }

    submits = args.submits_today if args.submits_today >= 0 else None
    result = authorize_submission(
        package_input,
        run_id=args.run_id,
        ledger=ledger,
        submits_today=submits,
        require_form_lock=not args.dry_run,
        dry_run=args.dry_run,
    )

    if ledger is not None:
        env = make_envelope(
            run_id=args.run_id,
            producer=PRODUCER,
            artifact_type=ARTIFACT_TYPE_PACKAGE,
            payload=result.package,
            job_key=result.package["job_key"],
            task_id=f"{args.run_id}:authorize",
            status=result.state,
            evidence_refs=result.package.get("evidence_refs")
            if isinstance(result.package.get("evidence_refs"), list)
            else [result.package["canonical_url"]],
            blocking_reasons=result.blocking_reasons,
            retryable=bool(result.package.get("retryable")),
        )
        # evidence_refs on package may be absent — fix envelope
        if not env["evidence_refs"]:
            env["evidence_refs"] = [result.package["canonical_url"]]
        ledger.append_artifact(env)
        ledger.transition_job(
            result.package["job_key"],
            canonical_url=result.package["canonical_url"],
            status=result.sop_status,
            run_id=args.run_id,
            organization=result.package.get("organization") or "",
            role=result.package.get("role") or "",
            meta={"authorize_state": result.state, "authorized": result.authorized},
        )
        ledger.set_phase(args.run_id, "authorize")
        ledger.mark_task(
            f"{args.run_id}:authorize",
            args.run_id,
            "authorize",
            "complete",
            finished=True,
            detail={"state": result.state, "authorized": result.authorized},
        )
        ledger.close()

    payload = result.to_dict()
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "package"}, indent=2))
    print(json.dumps({"package_state": result.state, "authorized": result.authorized}))
    return 0 if (result.authorized or result.state == STATE_READY_FOR_APPROVAL) else 2


if __name__ == "__main__":
    raise SystemExit(_cli())
