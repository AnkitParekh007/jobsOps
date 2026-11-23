#!/usr/bin/env python3
"""F05/F09 submission authorize gate — deterministic; never auto-retry after uncertain."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
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
from user_workspace import (  # noqa: E402
    identity_markers_present,
    load_candidate_profile,
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

# Materials → Ready for approval: only independently derived materials gates.
# hard_eligibility / filenames / session require evidence objects for SubmissionAuthorized.
READY_CHECKLIST = (
    "pdf_validated",
    "fingerprint_matches_scores",
    "ats_gate",
    "quality_gate",
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


def validate_pdf_file(path: Path) -> tuple[bool, str, bytes]:
    """
    Validate that path exists and looks like a real PDF.
    Returns (ok, reason, raw_bytes).
    """
    p = Path(path)
    if not p.is_file():
        return False, "pdf_missing", b""
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return False, f"pdf_unreadable:{exc}", b""
    if not raw.startswith(PDF_MAGIC):
        return False, "pdf_invalid_magic", raw
    if len(raw) < 64:
        return False, "pdf_too_small", raw
    return True, "ok", raw


def recompute_pdf_fingerprint(path: Path) -> tuple[bool, str, str, str]:
    """
    Recompute SHA-256 of the actual PDF bytes.
    Returns (ok, reason, fingerprint, method).
    """
    ok, reason, raw = validate_pdf_file(path)
    if not ok:
        return False, reason, "", ""
    return True, "ok", fingerprint_bytes(raw), "sha256_bytes"


def extract_pdf_text(path: Path) -> str:
    """
    Best-effort PDF text extract for E07.
    Prefers pypdf when installed; falls back to deterministic pdf_fixture parser.
    """
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError:
            PdfReader = None  # type: ignore
    if PdfReader is not None:
        try:
            reader = PdfReader(str(path))
            parts: list[str] = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            joined = "\n".join(parts).strip()
            if joined:
                return joined
        except Exception:  # noqa: BLE001
            pass
    try:
        from pdf_fixture import extract_text_ordered

        text, _pages = extract_text_ordered(Path(path))
        return text
    except Exception:  # noqa: BLE001
        return ""


def reserve_daily_submission(
    ledger: Ledger,
    *,
    job_key: str,
    run_id: str,
    cap: int = DAILY_SUBMIT_CAP,
    submit_date: Optional[str] = None,
    reservation_id: Optional[str] = None,
) -> tuple[bool, str, Optional[str]]:
    """
    Atomically reserve one daily submit slot (cross-process safe via SQLite).
    Requires OrchestratorContext with ``reserve_submit`` scope.
    """
    import uuid

    day = submit_date or datetime_today_kolkata()
    rid = reservation_id or f"res_{uuid.uuid4().hex}"
    return ledger.reserve_submission_slot(
        reservation_id=rid,
        job_key=job_key,
        run_id=run_id,
        submit_date=day,
        cap=cap,
    )


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
    identity_markers: Optional[Sequence[str]] = None,
    allow_fixture_method: bool = False,
) -> tuple[bool, list[str]]:
    """E07 materials gates: floors, fingerprint match, no invented skills."""
    blocking: list[str] = []
    if not pdf_fingerprint or not str(pdf_fingerprint).strip():
        blocking.append("missing_pdf_fingerprint")
    allowed_methods = set(LIVE_FINGERPRINT_METHODS)
    if allow_fixture_method:
        allowed_methods |= FIXTURE_FINGERPRINT_METHODS
    if fingerprint_method not in allowed_methods:
        if fingerprint_method in FIXTURE_FINGERPRINT_METHODS:
            blocking.append("fixture_evidence_rejected_on_live_path")
        else:
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

    # Identity markers from private profile (never hardcoded personal names).
    if not (extracted_text or "").strip():
        blocking.append("empty_pdf_extract")
    else:
        markers = [str(m) for m in (identity_markers or []) if str(m).strip()]
        if not markers:
            blocking.append("identity_markers_missing")
        elif not identity_markers_present(extracted_text, markers):
            blocking.append("identity_not_in_pdf_extract")

    return len(blocking) == 0, blocking


# Evidence keys that must be independently verified — agent checklist booleans are not proof.
INDEPENDENT_EVIDENCE_KEYS = (
    "posting_open",
    "not_duplicate",
    "hard_eligibility_met",
    "filenames_correct",
    "required_fields_complete",
    "screening_answers_verified",
    "no_auth_wall",
    "portal_session",
    "user_consent",
)

TRUSTED_EVIDENCE_KIND = "trusted_evidence_v1"
EVIDENCE_SECRET_ENV = "JOBOPS_EVIDENCE_SECRET"
# Publicly known insecure value — rejected on every path (including if set in env).
_KNOWN_INSECURE_EVIDENCE_SECRETS = frozenset(
    {
        b"jobops-dev-evidence-secret-not-for-production",
        b"changeme",
        b"secret",
        b"test",
    }
)
FIXTURE_FINGERPRINT_METHODS = frozenset({"fixture"})
LIVE_FINGERPRINT_METHODS = frozenset({"sha256_bytes", "sha256_normalized_text"})
PDF_MAGIC = b"%PDF"


class EvidenceSecretError(RuntimeError):
    """No secure installation-specific evidence signing key is available."""


def evidence_secret(*, workspace_home: Optional[Path] = None) -> bytes:
    """
    Resolve HMAC secret for trusted evidence.

    Prefer env, then private workspace file. Fail closed when unavailable.
    Never returns a publicly known fallback secret.
    """
    env = (os.environ.get(EVIDENCE_SECRET_ENV) or "").strip()
    if env:
        raw = env.encode("utf-8")
        if raw in _KNOWN_INSECURE_EVIDENCE_SECRETS or len(raw) < 16:
            raise EvidenceSecretError("evidence_secret_insecure_or_too_short")
        return raw
    if workspace_home is not None:
        path = Path(workspace_home) / "secrets" / "evidence_hmac.key"
        if path.is_file():
            raw = path.read_bytes().strip()
            if raw in _KNOWN_INSECURE_EVIDENCE_SECRETS or len(raw) < 16:
                raise EvidenceSecretError("evidence_secret_insecure_or_too_short")
            if raw:
                return raw
    raise EvidenceSecretError("evidence_secret_unavailable")


def _evidence_payload_str(
    *,
    claim: str,
    user_id: str,
    job_key: str,
    session_id: str,
    artifact_fingerprint: str,
    issuer: str,
    issued_at: int,
    expires_at: int,
    nonce: str,
) -> str:
    return "|".join(
        [
            claim,
            user_id,
            job_key,
            session_id,
            artifact_fingerprint,
            issuer,
            str(issued_at),
            str(expires_at),
            nonce,
        ]
    )


def issue_trusted_evidence(
    *,
    claim: str,
    user_id: str,
    job_key: str,
    session_id: str,
    artifact_fingerprint: str,
    issuer: str = "jobops.authorize",
    ttl_sec: int = 3600,
    secret: Optional[bytes] = None,
    now: Optional[int] = None,
) -> dict[str, Any]:
    """
    Mint a signed evidence record. Only deterministic code holding the secret can issue.
    Agents cannot forge valid records without the HMAC key.
    """
    import secrets as _secrets
    import time

    issued_at = int(now if now is not None else time.time())
    expires_at = issued_at + int(ttl_sec)
    nonce = _secrets.token_hex(8)
    key = secret if secret is not None else evidence_secret()
    payload = _evidence_payload_str(
        claim=claim,
        user_id=user_id,
        job_key=job_key,
        session_id=session_id,
        artifact_fingerprint=artifact_fingerprint,
        issuer=issuer,
        issued_at=issued_at,
        expires_at=expires_at,
        nonce=nonce,
    )
    sig = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "kind": TRUSTED_EVIDENCE_KIND,
        "claim": claim,
        "user_id": user_id,
        "job_key": job_key,
        "session_id": session_id,
        "artifact_fingerprint": artifact_fingerprint,
        "issuer": issuer,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "nonce": nonce,
        "sig": sig,
    }


def issue_consent_record(
    *,
    user_id: str,
    job_key: str,
    session_id: str,
    artifact_fingerprint: str,
    approval_id: str,
    secret: Optional[bytes] = None,
    ttl_sec: int = 3600,
) -> dict[str, Any]:
    """Consent bound to user + requisition + form session + artifact fingerprint."""
    rec = issue_trusted_evidence(
        claim="user_consent",
        user_id=user_id,
        job_key=job_key,
        session_id=session_id,
        artifact_fingerprint=artifact_fingerprint,
        issuer="jobops.consent",
        ttl_sec=ttl_sec,
        secret=secret,
    )
    rec["approval_id"] = approval_id
    # Re-sign including approval_id binding.
    key = secret if secret is not None else evidence_secret()
    payload = (
        _evidence_payload_str(
            claim=rec["claim"],
            user_id=rec["user_id"],
            job_key=rec["job_key"],
            session_id=rec["session_id"],
            artifact_fingerprint=rec["artifact_fingerprint"],
            issuer=rec["issuer"],
            issued_at=int(rec["issued_at"]),
            expires_at=int(rec["expires_at"]),
            nonce=str(rec["nonce"]),
        )
        + f"|{approval_id}"
    )
    rec["sig"] = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return rec


def verify_trusted_evidence(
    record: Mapping[str, Any],
    *,
    expected_claim: str,
    user_id: str,
    job_key: str,
    session_id: str,
    artifact_fingerprint: str,
    secret: Optional[bytes] = None,
    now: Optional[int] = None,
    require_approval_id: Optional[str] = None,
) -> tuple[bool, str]:
    """Deterministic verification of a trusted evidence / consent record."""
    import time

    if not isinstance(record, Mapping):
        return False, "evidence_not_mapping"
    if record.get("kind") != TRUSTED_EVIDENCE_KIND:
        return False, "evidence_untrusted_kind"
    if record.get("claim") != expected_claim:
        return False, "evidence_claim_mismatch"
    # Binding checks — reject cross-job / cross-user / cross-session forgeries.
    if str(record.get("user_id") or "") != str(user_id):
        return False, "evidence_user_mismatch"
    if str(record.get("job_key") or "") != str(job_key):
        return False, "evidence_job_mismatch"
    if str(record.get("session_id") or "") != str(session_id):
        return False, "evidence_session_mismatch"
    if str(record.get("artifact_fingerprint") or "") != str(artifact_fingerprint):
        return False, "evidence_fingerprint_mismatch"
    try:
        expires_at = int(record["expires_at"])
        issued_at = int(record["issued_at"])
    except (KeyError, TypeError, ValueError):
        return False, "evidence_timestamps_invalid"
    ts = int(now if now is not None else time.time())
    if expires_at < ts:
        return False, "evidence_expired"
    if issued_at > ts + 60:
        return False, "evidence_issued_in_future"
    nonce = str(record.get("nonce") or "")
    sig = str(record.get("sig") or "")
    if not nonce or not sig:
        return False, "evidence_missing_sig"
    key = secret if secret is not None else evidence_secret()
    payload = _evidence_payload_str(
        claim=str(record.get("claim")),
        user_id=str(record.get("user_id")),
        job_key=str(record.get("job_key")),
        session_id=str(record.get("session_id")),
        artifact_fingerprint=str(record.get("artifact_fingerprint")),
        issuer=str(record.get("issuer") or ""),
        issued_at=issued_at,
        expires_at=expires_at,
        nonce=nonce,
    )
    if require_approval_id is not None or expected_claim == "user_consent":
        approval = str(record.get("approval_id") or require_approval_id or "")
        if not approval:
            return False, "evidence_consent_missing_approval"
        payload = payload + f"|{approval}"
        if require_approval_id is not None and approval != require_approval_id:
            return False, "evidence_approval_mismatch"
    expected = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False, "evidence_sig_invalid"
    return True, "ok"


def _binding_context(
    evidence: Mapping[str, Any],
    *,
    job_key: str,
    artifact_fingerprint: str,
) -> dict[str, str]:
    """Extract binding fields used to verify trusted evidence."""
    session = evidence.get("portal_session")
    session_id = ""
    if isinstance(session, Mapping):
        session_id = str(session.get("session_id") or "")
    if not session_id:
        session_id = str(evidence.get("session_id") or "")
    user_id = str(evidence.get("user_id") or evidence.get("candidate_id") or "")
    if not user_id:
        consent = evidence.get("user_consent")
        if isinstance(consent, Mapping):
            user_id = str(consent.get("user_id") or "")
    return {
        "user_id": user_id,
        "job_key": job_key,
        "session_id": session_id,
        "artifact_fingerprint": artifact_fingerprint,
    }


def _evidence_truth(
    evidence: Mapping[str, Any],
    key: str,
    *,
    job_key: str = "",
    artifact_fingerprint: str = "",
    secret: Optional[bytes] = None,
) -> tuple[bool, Optional[str]]:
    """
    Independently verify an authorization claim from evidence_package.
    Requires trusted_evidence_v1 HMAC records bound to user/job/session/fingerprint.
    Rejects bare booleans and self-asserted verified=true objects.
    """
    if key not in evidence:
        return False, f"evidence_missing:{key}"
    val = evidence[key]
    if val is True:
        return False, f"evidence_untrusted_boolean:{key}"
    if val is False or val is None:
        return False, f"evidence_false:{key}"
    if isinstance(val, str) and val.strip():
        # Opaque strings are not proof.
        return False, f"evidence_untrusted_string:{key}"
    if not isinstance(val, Mapping):
        return False, f"evidence_invalid:{key}"

    # Self-asserted shapes (verified=true without HMAC) are explicitly rejected.
    if val.get("kind") != TRUSTED_EVIDENCE_KIND:
        if val.get("verified") is True:
            return False, f"evidence_self_asserted:{key}"
        if val.get("status") == "authorized":
            return False, f"evidence_self_asserted_session:{key}"
        if val.get("consent") is True or val.get("consent_id"):
            return False, f"evidence_self_asserted_consent:{key}"
        return False, f"evidence_untrusted_kind:{key}"

    binding = _binding_context(
        evidence, job_key=job_key, artifact_fingerprint=artifact_fingerprint
    )
    # Prefer bindings embedded on the record itself when context is incomplete.
    user_id = binding["user_id"] or str(val.get("user_id") or "")
    session_id = binding["session_id"] or str(val.get("session_id") or "")
    fp = binding["artifact_fingerprint"] or str(val.get("artifact_fingerprint") or "")
    jk = binding["job_key"] or str(val.get("job_key") or "")
    if not user_id or not session_id or not fp or not jk:
        return False, f"evidence_binding_incomplete:{key}"

    ok, reason = verify_trusted_evidence(
        val,
        expected_claim=key,
        user_id=user_id,
        job_key=jk,
        session_id=session_id,
        artifact_fingerprint=fp,
        secret=secret,
        require_approval_id=str(val.get("approval_id")) if key == "user_consent" else None,
    )
    if not ok:
        return False, f"{reason}:{key}"
    return True, None


def derive_authorization_checklist(
    *,
    materials_ok: bool,
    ats: float,
    quality: float,
    fingerprint: str,
    ats_fp: Optional[str],
    qual_fp: Optional[str],
    cap_ok: bool,
    lock_held: bool,
    evidence: Mapping[str, Any],
    consent_auto_submit: bool,
    user_approved: bool,
    job_key: str = "",
    secret: Optional[bytes] = None,
) -> tuple[dict[str, bool], list[str]]:
    """
    Build checklist from independent verification only.
    Agent-supplied checklist booleans are ignored as proof.
    """
    checklist = default_checklist()
    blocking: list[str] = []

    checklist["ats_gate"] = ats >= ATS_FLOOR
    checklist["quality_gate"] = quality >= QUALITY_FLOOR
    checklist["fingerprint_matches_scores"] = (
        bool(fingerprint) and ats_fp == fingerprint and qual_fp == fingerprint
    )
    checklist["pdf_validated"] = bool(materials_ok)
    checklist["daily_cap_allows"] = bool(cap_ok)
    checklist["form_lock_held"] = bool(lock_held)
    checklist["auto_submit_or_user_approved"] = bool(consent_auto_submit and user_approved)

    for key in (
        "posting_open",
        "not_duplicate",
        "hard_eligibility_met",
        "filenames_correct",
        "required_fields_complete",
        "screening_answers_verified",
        "no_auth_wall",
    ):
        ok, reason = _evidence_truth(
            evidence, key, job_key=job_key, artifact_fingerprint=fingerprint, secret=secret
        )
        checklist[key] = ok
        if not ok and reason:
            blocking.append(reason)

    session_ok, session_reason = _evidence_truth(
        evidence,
        "portal_session",
        job_key=job_key,
        artifact_fingerprint=fingerprint,
        secret=secret,
    )
    checklist["session_authorized_if_needed"] = session_ok
    if not session_ok and session_reason:
        blocking.append(session_reason)

    consent_ok, consent_reason = _evidence_truth(
        evidence,
        "user_consent",
        job_key=job_key,
        artifact_fingerprint=fingerprint,
        secret=secret,
    )
    if not consent_ok:
        # No fallback to bare approval_id — consent must be a bound trusted record.
        if consent_reason:
            blocking.append(consent_reason)
        checklist["auto_submit_or_user_approved"] = False
    else:
        checklist["auto_submit_or_user_approved"] = bool(consent_auto_submit)
        if not consent_auto_submit:
            blocking.append("consent_auto_submit_disabled")

    return checklist, blocking


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
    identity_markers: Optional[Sequence[str]] = None,
    consent_auto_submit: Optional[bool] = None,
    workspace_home: Optional[Path] = None,
) -> AuthorizeResult:
    """
    Deterministic gate before any browser submit.

    dry_run=True stops at ReadyForApproval when materials pass (no SubmissionAuthorized).
    Never auto-retries after SubmissionUncertain (prior_uncertain → block).
    Agent-supplied checklist booleans are never treated as proof.
    """
    url = str(package_input.get("canonical_url") or "")
    if not url.startswith("http"):
        raise ContractError("canonical_url required")
    canon = normalize_url(url)
    jk = str(package_input.get("job_key") or job_key_from_url(canon))

    # Hard rule: never retry uncertain without Phase 4 reconcile
    ledger_uncertain = bool(
        ledger is not None and ledger.has_uncertain_reservation(job_key=jk)
    )
    if prior_uncertain or package_input.get("state") == STATE_UNCERTAIN or ledger_uncertain:
        reason = (
            "submission_reservation:job_uncertain_no_retry"
            if ledger_uncertain
            else "prior_submission_uncertain_no_auto_retry"
        )
        pkg = build_application_package(
            job_key=jk,
            canonical_url=canon,
            run_id=run_id,
            state=STATE_UNCERTAIN,
            ats_score=float(package_input.get("ats_score") or 0),
            quality_score=float(package_input.get("quality_score") or 0),
            pdf_fingerprint=str(package_input.get("pdf_fingerprint") or "none"),
            fingerprint_method=str(package_input.get("fingerprint_method") or "fixture"),
            checklist=default_checklist(),
            blocking_reasons=[reason],
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
            blocking_reasons=[reason],
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
            checklist=default_checklist(),
            blocking_reasons=blocking,
            policy_version=policy_version,
        )
        return AuthorizeResult(
            False, STATE_PREPARING, SOP_STATUS_MAP[STATE_PREPARING], pkg, blocking, tool.code, tool.message
        )

    # Load identity + consent from private workspace (never trust package booleans alone).
    profile = load_candidate_profile(home=workspace_home, allow_missing=True)
    markers = list(identity_markers or [])
    if not markers:
        markers = list(profile.identity_markers)
    if not markers and package_input.get("identity_markers"):
        markers = [str(m) for m in package_input["identity_markers"] if str(m).strip()]
    auto_submit = (
        bool(consent_auto_submit)
        if consent_auto_submit is not None
        else bool(profile.consent.get("auto_submit_enabled"))
    )
    # Global kill switches — external submit disabled by default.
    if os.environ.get("JOBOPS_ALLOW_SUBMIT", "0") != "1":
        auto_submit = False
    live_submit = os.environ.get("JOBOPS_ENABLE_LIVE_SUBMIT", "0") == "1"
    allow_fixture = os.environ.get("JOBOPS_ALLOW_FIXTURE_EVIDENCE", "0") == "1"
    # Live portal paths never accept fixture fingerprints.
    # dry-run may use fixture digests; non-dry authorize needs override or real PDF.
    live_pdf_path = bool(live_submit) or bool(package_input.get("require_live_pdf"))
    reject_fixture = live_submit or (not dry_run and not allow_fixture)

    try:
        evidence_key = evidence_secret(workspace_home=workspace_home)
    except EvidenceSecretError as exc:
        pkg = build_application_package(
            job_key=jk,
            canonical_url=canon,
            run_id=run_id,
            state=STATE_PREPARING,
            ats_score=float(package_input.get("ats_score") or 0),
            quality_score=float(package_input.get("quality_score") or 0),
            pdf_fingerprint=str(package_input.get("pdf_fingerprint") or "none"),
            fingerprint_method=str(package_input.get("fingerprint_method") or "fixture"),
            checklist=default_checklist(),
            blocking_reasons=[f"evidence_secret:{exc}"],
            policy_version=policy_version,
        )
        return AuthorizeResult(
            False,
            STATE_PREPARING,
            SOP_STATUS_MAP[STATE_PREPARING],
            pkg,
            [f"evidence_secret:{exc}"],
            "evidence_secret_unavailable",
            str(exc),
        )

    extracted = str(package_input.get("extracted_text") or "")
    pdf_path = package_input.get("pdf_path")
    fingerprint = str(package_input.get("pdf_fingerprint") or "")
    method = str(package_input.get("fingerprint_method") or "fixture")
    pdf_blocking: list[str] = []

    # Live / production paths: require real PDF, recompute fingerprint, reject fixtures.
    if reject_fixture or live_pdf_path or live_submit:
        if not pdf_path:
            if reject_fixture and method in FIXTURE_FINGERPRINT_METHODS:
                pdf_blocking.append("fixture_evidence_rejected_on_live_path")
            elif live_submit or live_pdf_path:
                pdf_blocking.append("pdf_path_required_on_live_path")
        else:
            ok_pdf, pdf_reason, recomputed, recomputed_method = recompute_pdf_fingerprint(
                Path(str(pdf_path))
            )
            if not ok_pdf:
                pdf_blocking.append(pdf_reason)
            else:
                if fingerprint and fingerprint != recomputed:
                    pdf_blocking.append("pdf_fingerprint_mismatch_recomputed")
                fingerprint = recomputed
                method = recomputed_method
                if not extracted:
                    extracted = extract_pdf_text(Path(str(pdf_path)))
    elif pdf_path and Path(str(pdf_path)).is_file():
        # Soft path: recompute when file present even for dry-run.
        ok_pdf, pdf_reason, recomputed, recomputed_method = recompute_pdf_fingerprint(
            Path(str(pdf_path))
        )
        if ok_pdf:
            if fingerprint and fingerprint != recomputed:
                pdf_blocking.append("pdf_fingerprint_mismatch_recomputed")
            fingerprint = recomputed
            method = recomputed_method
            if not extracted:
                extracted = extract_pdf_text(Path(str(pdf_path)))
        elif not fingerprint:
            pdf_blocking.append(pdf_reason)

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
    # After recompute, score fingerprints must match the recomputed digest.
    if fingerprint and method in LIVE_FINGERPRINT_METHODS:
        if ats_fp_s and ats_fp_s != fingerprint:
            # Keep mismatch detection in validate_materials.
            pass
        elif not ats_fp_s:
            ats_fp_s = fingerprint
        if qual_fp_s and qual_fp_s != fingerprint:
            pass
        elif not qual_fp_s:
            qual_fp_s = fingerprint

    materials_ok, mat_blocking = validate_materials(
        extracted_text=extracted,
        ats_score=ats,
        quality_score=quality,
        pdf_fingerprint=fingerprint or "missing",
        ats_score_fingerprint=ats_fp_s,
        quality_score_fingerprint=qual_fp_s,
        fingerprint_method=method,
        identity_markers=markers,
        allow_fixture_method=(not live_submit) and (allow_fixture or dry_run),
    )
    if pdf_blocking:
        materials_ok = False
        mat_blocking = list(mat_blocking) + pdf_blocking

    # Daily cap — independent ledger/count check (includes atomic reservations).
    if submits_today is None:
        submits_today = count_submits_today(ledger)
        if ledger is not None:
            submits_today = max(
                submits_today,
                ledger.count_submission_reservations(submit_date=datetime_today_kolkata()),
            )
    cap_verdict = check_daily_submit_cap(submits_today, cap=DAILY_SUBMIT_CAP)
    remaining = daily_submit_remaining(submits_today, cap=DAILY_SUBMIT_CAP)
    daily_cap_info = {
        "cap": DAILY_SUBMIT_CAP,
        "submits_today": submits_today,
        "remaining": remaining,
    }

    # Session / form lock — ledger is source of truth when require_form_lock
    lock_info = check_form_lock(ledger, canonical_url=canon, run_id=run_id)
    if require_form_lock:
        lock_held = bool(lock_info.get("held"))
    else:
        # Tests may omit ledger; still refuse agent checklist alone — need session_lock object.
        sess = package_input.get("session_lock") or {}
        lock_held = bool(isinstance(sess, Mapping) and sess.get("held") and sess.get("lock_id"))
        if sess:
            lock_info = dict(sess)

    evidence = dict(package_input.get("evidence_package") or {})
    evidence.setdefault("ats_floor", ATS_FLOOR)
    evidence.setdefault("quality_floor", QUALITY_FLOOR)
    evidence["materials_ok"] = materials_ok
    evidence["materials_blocking"] = mat_blocking
    evidence["checklist_source"] = "independent_derivation"
    evidence["ignored_agent_checklist"] = True

    # user_approved is derived only from a bound trusted consent record (not bare approval_id).
    consent_rec = evidence.get("user_consent")
    user_approved = bool(
        isinstance(consent_rec, Mapping) and consent_rec.get("kind") == TRUSTED_EVIDENCE_KIND
    )
    # When a ledger is present, consent must also match a durable approval row.
    if user_approved and ledger is not None and isinstance(consent_rec, Mapping):
        approval_id = str(consent_rec.get("approval_id") or evidence.get("approval_id") or "")
        if approval_id:
            ok_appr, appr_reason, _ = ledger.require_approved(
                approval_id,
                user_id=str(consent_rec.get("user_id") or evidence.get("user_id") or ""),
                job_key=jk,
                session_id=str(consent_rec.get("session_id") or evidence.get("session_id") or ""),
                artifact_fingerprint=fingerprint or "",
            )
            if not ok_appr:
                user_approved = False
                evidence["approval_binding_error"] = appr_reason
        else:
            user_approved = False
            evidence["approval_binding_error"] = "consent_missing_approval_id"

    checklist, evidence_blocking = derive_authorization_checklist(
        materials_ok=materials_ok,
        ats=ats,
        quality=quality,
        fingerprint=fingerprint or "",
        ats_fp=ats_fp_s,
        qual_fp=qual_fp_s,
        cap_ok=cap_verdict.ok,
        lock_held=lock_held,
        evidence=evidence,
        consent_auto_submit=auto_submit,
        user_approved=user_approved,
        job_key=jk,
        secret=evidence_key,
    )

    blocking: list[str] = []
    if not materials_ok:
        blocking.extend(mat_blocking)
    # Evidence gaps only block full authorize / ready-for-approval completeness,
    # not materials validation itself.

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

    # Cap exhausted → stay Ready for approval with explicit block (even before consent path).
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

    # Ready for approval — materials + floors pass (default / dry-run path).
    # When the caller requested auto-submit but evidence/consent failed, still
    # surface independent evidence_blocking reasons (do not hide forge failures).
    needs_human = bool(package_input.get("require_human_approval")) or not checklist.get(
        "auto_submit_or_user_approved", False
    )
    if dry_run or (needs_human and not auto_submit):
        extra_block: list[str] = []
        if dry_run:
            extra_block.append("dry_run_ready_for_approval")
        if not checklist.get("auto_submit_or_user_approved", False):
            extra_block.append("human_approval_required")
        if not auto_submit:
            extra_block.append("submit_disabled_by_default")
        # Include evidence gaps so forged/self-asserted packages are auditable.
        for reason in evidence_blocking:
            if reason not in extra_block:
                extra_block.append(reason)
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
            evidence_package={
                **evidence,
                "ready_for_approval": True,
                **({"dry_run": True} if dry_run else {}),
            },
            notes="Ready for approval — materials validated; no live submit",
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

    # Auto-submit requested but consent/evidence incomplete → fall through to
    # full authorize path so forge/mismatch reasons are returned explicitly.
    if needs_human and auto_submit:
        blocking.extend(evidence_blocking)
        if not checklist.get("auto_submit_or_user_approved", False):
            blocking.append("human_approval_required")
        # Continue into lock + submit checklist gates below.

    # Full authorize path — independent evidence required (ignore agent checklist).
    blocking.extend(evidence_blocking)

    if not checklist.get("form_lock_held"):
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
    if submit_fail or evidence_blocking:
        blocking.extend([f"checklist:{k}" for k in submit_fail if f"checklist:{k}" not in blocking])
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
            notes="submit evidence incomplete — agent checklist booleans ignored",
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
            "Ready for approval; independent evidence incomplete for auto-submit",
        )

    reservation_meta: dict[str, Any] = {}
    if not dry_run:
        # Successful authorization always requires a valid atomic reservation.
        from trust_boundary import current_orchestrator

        if ledger is None:
            blocking.append("submission_reservation:ledger_required")
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
                notes="reservation unavailable — ledger required for authorize",
                retryable=True,
                policy_version=policy_version,
            )
            return AuthorizeResult(
                False,
                STATE_READY_FOR_APPROVAL,
                SOP_STATUS_MAP[STATE_READY_FOR_APPROVAL],
                pkg,
                blocking,
                "reservation_unavailable",
                "ledger_required",
            )
        if current_orchestrator() is None:
            blocking.append("submission_reservation:orchestrator_required")
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
                notes="reservation unavailable — orchestrator context required",
                retryable=True,
                policy_version=policy_version,
            )
            return AuthorizeResult(
                False,
                STATE_READY_FOR_APPROVAL,
                SOP_STATUS_MAP[STATE_READY_FOR_APPROVAL],
                pkg,
                blocking,
                "reservation_unavailable",
                "orchestrator_required",
            )
        blocked_ident, ident_reason = ledger.has_blocking_application_identity(jk)
        if blocked_ident:
            blocking.append(f"application_identity:{ident_reason}")
            uncertain = ident_reason.endswith("uncertain")
            pkg = build_application_package(
                job_key=jk,
                canonical_url=canon,
                run_id=run_id,
                state=STATE_UNCERTAIN if uncertain else STATE_READY_FOR_APPROVAL,
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
                notes="permanent application-identity guard — blocked across dates/runs",
                retryable=False,
                policy_version=policy_version,
            )
            return AuthorizeResult(
                False,
                STATE_UNCERTAIN if uncertain else STATE_READY_FOR_APPROVAL,
                SOP_STATUS_MAP[STATE_UNCERTAIN if uncertain else STATE_READY_FOR_APPROVAL],
                pkg,
                blocking,
                "application_identity" if not uncertain else "submission_uncertain",
                ident_reason,
            )
        if ledger.has_uncertain_reservation(job_key=jk):
            blocking.append("submission_reservation:job_uncertain_no_retry")
            pkg = build_application_package(
                job_key=jk,
                canonical_url=canon,
                run_id=run_id,
                state=STATE_UNCERTAIN,
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
                notes="prior uncertain reservation — no retry",
                retryable=False,
                policy_version=policy_version,
            )
            return AuthorizeResult(
                False,
                STATE_UNCERTAIN,
                SOP_STATUS_MAP[STATE_UNCERTAIN],
                pkg,
                blocking,
                "submission_uncertain",
                "job_uncertain_no_retry",
            )
        ok_res, res_reason, res_id = reserve_daily_submission(
            ledger, job_key=jk, run_id=run_id, cap=DAILY_SUBMIT_CAP
        )
        reservation_meta = {
            "reservation_ok": ok_res,
            "reservation_reason": res_reason,
            "reservation_id": res_id,
        }
        if not ok_res:
            blocking.append(f"submission_reservation:{res_reason}")
            daily_cap_info = {**daily_cap_info, **reservation_meta}
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
                notes="daily reservation refused — concurrent cap or duplicate",
                retryable=res_reason != "job_uncertain_no_retry",
                policy_version=policy_version,
            )
            return AuthorizeResult(
                False,
                STATE_READY_FOR_APPROVAL,
                SOP_STATUS_MAP[STATE_READY_FOR_APPROVAL],
                pkg,
                blocking,
                "daily_submit_cap",
                res_reason,
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
        daily_cap={**daily_cap_info, **reservation_meta},
        evidence_package={**evidence, "authorized": True, **reservation_meta},
        notes="SubmissionAuthorized — independent evidence verified; browser submit may proceed once",
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
        "all independent gates passed",
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
    reservation_id: Optional[str] = None,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    """
    Map post-submit evidence → Applied | Submitted | SubmissionUncertain.
    Uncertain is never retryable and must not be recorded as Applied.

    When a reservation_id is provided, Applied/Submitted consumes it and
    SubmissionUncertain marks the reservation uncertain (no retry / no re-reserve).
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
        "reservation_id": reservation_id,
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
                "reservation_id": reservation_id,
            },
        )
        if reservation_id:
            # Ownership-checked state transition; authority already enforced at reserve.
            if outcome in {STATE_APPLIED, "Submitted"}:
                ledger.consume_submission_reservation(
                    reservation_id,
                    run_id=run_id,
                    job_key=job_key,
                    require_authority=False,
                )
            elif outcome == STATE_UNCERTAIN:
                ledger.mark_submission_reservation_uncertain(
                    reservation_id,
                    run_id=run_id,
                    job_key=job_key,
                    require_authority=False,
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
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Stop at ReadyForApproval (never SubmissionAuthorized). "
            "Does not perform live portal submit; may still write ledger artifacts "
            "when --db is provided."
        ),
    )
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
