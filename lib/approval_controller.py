#!/usr/bin/env python3
"""
Authenticated approval controller.

New approvals always start as ``pending``. Only an authenticated user action
bound to a stored, single-use session (issued by SessionIssuer for a specific
pending approval) may transition them to ``approved``. Arbitrary user IDs,
fabricated tokens, expired sessions, and replayed approvals are rejected.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from ledger import Ledger  # noqa: E402
from trust_boundary import (  # noqa: E402
    agent_role_from_env,
    is_untrusted_agent_role,
    require_orchestrator,
)

DEFAULT_SESSION_TTL_SEC = 900


class ApprovalAuthError(PermissionError):
    """Raised when approval create/decide is refused."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class UserSession:
    """
    Authenticated end-user session for approval decisions.

    Constructing this dataclass alone is insufficient — verify/consume requires
    a matching stored row issued by SessionIssuer.
    """

    user_id: str
    session_token: str
    session_id: str
    approval_id: str
    auth_method: str = "cli_session"
    expires_at: str = ""

    def fingerprint(self) -> str:
        return hashlib.sha256(
            f"{self.user_id}|{self.auth_method}|{self.session_id}|{self.approval_id}|{self.session_token}".encode(
                "utf-8"
            )
        ).hexdigest()


class SessionIssuer:
    """Trusted issuer of stored, approval-bound, single-use user sessions."""

    def __init__(self, ledger: Ledger) -> None:
        require_orchestrator("approve")
        if is_untrusted_agent_role(agent_role_from_env()):
            raise ApprovalAuthError("session_issuer_forbidden_in_agent_role")
        self.ledger = ledger

    def issue_for_approval(
        self,
        *,
        user_id: str,
        approval_id: str,
        explicit_user_action: bool,
        auth_method: str = "cli_session",
        ttl_sec: int = DEFAULT_SESSION_TTL_SEC,
        action_name: str = "approve",
    ) -> UserSession:
        """
        Mint a session bound to a pending approval for an authenticated principal.

        ``explicit_user_action`` must be True — callers must obtain a real user
        confirmation (TTY prompt / UI click) before setting this flag.
        """
        require_orchestrator("approve")
        if is_untrusted_agent_role(agent_role_from_env()):
            raise ApprovalAuthError("user_session_forbidden_in_agent_role")
        if not explicit_user_action:
            raise ApprovalAuthError("explicit_user_action_required")
        if not user_id or not str(user_id).strip():
            raise ApprovalAuthError("user_id_required")
        # Reject obviously fabricated / wildcard principals.
        uid = str(user_id).strip()
        if uid in {"*", "any", "admin", "root"} or uid.startswith("arbitrary:"):
            raise ApprovalAuthError("user_id_rejected")
        row = self.ledger.get_approval(approval_id)
        if row is None:
            raise ApprovalAuthError("approval_not_found")
        if action_name == "approve" and row["status"] != "pending":
            raise ApprovalAuthError(f"approval_not_pending:{row['status']}")
        if action_name == "revoke" and row["status"] not in {"pending", "approved"}:
            raise ApprovalAuthError(f"approval_not_revocable:{row['status']}")
        if action_name not in {"approve", "revoke"}:
            raise ApprovalAuthError(f"unsupported_session_action:{action_name}")
        if row["user_id"] != uid:
            raise ApprovalAuthError("user_session_user_mismatch")
        now = _utc_now()
        session_id = f"usess_{secrets.token_hex(16)}"
        token = secrets.token_hex(32)
        expires_at = _iso(now + timedelta(seconds=max(30, int(ttl_sec))))
        self.ledger.store_user_session(
            session_id=session_id,
            user_id=uid,
            approval_id=approval_id,
            token_hash=_token_hash(token),
            auth_method=auth_method,
            issued_at=_iso(now),
            expires_at=expires_at,
            explicit_action=action_name,
        )
        return UserSession(
            user_id=uid,
            session_token=token,
            session_id=session_id,
            approval_id=approval_id,
            auth_method=auth_method,
            expires_at=expires_at,
        )


def mint_user_session(
    user_id: str,
    *,
    approval_id: str,
    ledger: Ledger,
    explicit_user_action: bool,
    auth_method: str = "cli_session",
    ttl_sec: int = DEFAULT_SESSION_TTL_SEC,
) -> UserSession:
    """Create a fresh stored session bound to a pending approval (orchestrator only)."""
    return SessionIssuer(ledger).issue_for_approval(
        user_id=user_id,
        approval_id=approval_id,
        explicit_user_action=explicit_user_action,
        auth_method=auth_method,
        ttl_sec=ttl_sec,
    )


def verify_user_session(
    session: UserSession,
    *,
    expected_user_id: str,
    approval_id: str,
    ledger: Ledger,
    consume: bool = False,
) -> dict[str, Any]:
    """
    Verify session against stored state. Optionally consume (single-use approve).
    """
    if is_untrusted_agent_role(agent_role_from_env()):
        raise ApprovalAuthError("approval_forbidden_in_agent_role")
    if not session.user_id or session.user_id != expected_user_id:
        raise ApprovalAuthError("user_session_user_mismatch")
    if not session.session_token or len(session.session_token) < 32:
        raise ApprovalAuthError("user_session_token_invalid")
    if session.approval_id != approval_id:
        raise ApprovalAuthError("user_session_approval_mismatch")
    stored = ledger.get_user_session(session.session_id)
    if stored is None:
        raise ApprovalAuthError("user_session_not_found")
    if stored["user_id"] != expected_user_id:
        raise ApprovalAuthError("user_session_user_mismatch")
    if stored["approval_id"] != approval_id:
        raise ApprovalAuthError("user_session_approval_mismatch")
    if stored.get("consumed_at"):
        raise ApprovalAuthError("user_session_already_consumed")
    try:
        expires = _parse_iso(str(stored["expires_at"]))
    except ValueError as exc:
        raise ApprovalAuthError("user_session_expiry_invalid") from exc
    if expires <= _utc_now():
        raise ApprovalAuthError("user_session_expired")
    expected_hash = str(stored["token_hash"])
    actual_hash = _token_hash(session.session_token)
    if not hmac.compare_digest(expected_hash, actual_hash):
        raise ApprovalAuthError("user_session_token_mismatch")
    if consume:
        ok = ledger.consume_user_session(session.session_id)
        if not ok:
            raise ApprovalAuthError("user_session_consume_failed")
        stored = ledger.get_user_session(session.session_id) or stored
    return stored


class ApprovalController:
    """
    Sole sanctioned path for creating pending approvals and authenticating decisions.
    """

    def __init__(self, ledger: Ledger) -> None:
        require_orchestrator("record_approval")
        self.ledger = ledger

    def request_approval(
        self,
        *,
        approval_id: str,
        user_id: str,
        job_key: str,
        session_id: str,
        artifact_fingerprint: str,
        document_path: str = "",
        run_id: Optional[str] = None,
        meta: Optional[Mapping[str, Any]] = None,
        expires_at: Optional[str] = None,
    ) -> str:
        """Create a durable approval that starts ``pending``."""
        require_orchestrator("record_approval")
        if is_untrusted_agent_role(agent_role_from_env()):
            raise ApprovalAuthError("approval_create_forbidden_in_agent_role")
        if not user_id or user_id in {"*", "any", "admin", "root"}:
            raise ApprovalAuthError("user_id_rejected")
        return self.ledger.record_approval(
            approval_id=approval_id,
            user_id=user_id,
            job_key=job_key,
            session_id=session_id,
            artifact_fingerprint=artifact_fingerprint,
            document_path=document_path,
            status="pending",
            decided_by="",
            run_id=run_id,
            meta=dict(meta or {}),
            expires_at=expires_at,
            require_authority=True,
            allow_overwrite=False,
        )

    def approve(
        self,
        *,
        approval_id: str,
        user_session: UserSession,
        expected_job_key: str,
        expected_session_id: str,
        expected_fingerprint: str,
    ) -> dict[str, Any]:
        """
        Authenticated user action: pending → approved.

        Requires a stored, unexpired, single-use session bound to this approval.
        Replayed approvals and fabricated tokens are rejected.
        """
        require_orchestrator("approve")
        row = self.ledger.get_approval(approval_id)
        if row is None:
            raise ApprovalAuthError("approval_not_found")
        if row["status"] != "pending":
            raise ApprovalAuthError(f"approval_not_pending:{row['status']}")
        if row.get("expires_at"):
            try:
                if _parse_iso(str(row["expires_at"])) <= _utc_now():
                    raise ApprovalAuthError("approval_expired")
            except ValueError as exc:
                raise ApprovalAuthError("approval_expiry_invalid") from exc
        verify_user_session(
            user_session,
            expected_user_id=row["user_id"],
            approval_id=approval_id,
            ledger=self.ledger,
            consume=True,
        )
        if row["job_key"] != expected_job_key:
            raise ApprovalAuthError("approval_job_mismatch")
        if row["session_id"] != expected_session_id:
            raise ApprovalAuthError("approval_session_mismatch")
        if row["artifact_fingerprint"] != expected_fingerprint:
            raise ApprovalAuthError("approval_fingerprint_mismatch")
        meta = dict(row.get("meta") or {})
        meta["auth_method"] = user_session.auth_method
        meta["session_fp"] = user_session.fingerprint()
        meta["approval_session_id"] = user_session.session_id
        self.ledger.decide_approval(
            approval_id=approval_id,
            status="approved",
            decided_by=f"user:{user_session.user_id}",
            meta=meta,
            require_authority=True,
            require_pending=True,
        )
        decided = self.ledger.get_approval(approval_id)
        assert decided is not None
        return decided

    def revoke(
        self,
        *,
        approval_id: str,
        user_session: UserSession,
        reason: str = "",
    ) -> dict[str, Any]:
        require_orchestrator("approve")
        row = self.ledger.get_approval(approval_id)
        if row is None:
            raise ApprovalAuthError("approval_not_found")
        if row["status"] not in {"pending", "approved"}:
            raise ApprovalAuthError(f"approval_not_revocable:{row['status']}")
        verify_user_session(
            user_session,
            expected_user_id=row["user_id"],
            approval_id=approval_id,
            ledger=self.ledger,
            consume=True,
        )
        meta = dict(row.get("meta") or {})
        if reason:
            meta["revoke_reason"] = reason
        self.ledger.decide_approval(
            approval_id=approval_id,
            status="revoked",
            decided_by=f"user:{user_session.user_id}",
            meta=meta,
            require_authority=True,
            require_pending=False,
        )
        decided = self.ledger.get_approval(approval_id)
        assert decided is not None
        return decided


def constant_time_token_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
