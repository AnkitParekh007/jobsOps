#!/usr/bin/env python3
"""
Authenticated approval controller.

New approvals always start as ``pending``. Only an authenticated user action
executed inside OrchestratorContext may transition them to ``approved``.
Untrusted agent processes cannot create approved rows or decide approvals.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sys
from dataclasses import dataclass
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


class ApprovalAuthError(PermissionError):
    """Raised when approval create/decide is refused."""


@dataclass(frozen=True)
class UserSession:
    """Authenticated end-user session for approval decisions."""

    user_id: str
    session_token: str
    auth_method: str = "cli_session"

    def fingerprint(self) -> str:
        return hashlib.sha256(
            f"{self.user_id}|{self.auth_method}|{self.session_token}".encode("utf-8")
        ).hexdigest()


def mint_user_session(user_id: str, *, auth_method: str = "cli_session") -> UserSession:
    """Create a fresh authenticated session (orchestrator / CLI only)."""
    require_orchestrator("approve")
    if is_untrusted_agent_role(agent_role_from_env()):
        raise ApprovalAuthError("user_session_forbidden_in_agent_role")
    return UserSession(
        user_id=user_id,
        session_token=secrets.token_hex(32),
        auth_method=auth_method,
    )


def verify_user_session(session: UserSession, *, expected_user_id: str) -> None:
    if not session.user_id or session.user_id != expected_user_id:
        raise ApprovalAuthError("user_session_user_mismatch")
    if not session.session_token or len(session.session_token) < 32:
        raise ApprovalAuthError("user_session_token_invalid")
    if is_untrusted_agent_role(agent_role_from_env()):
        raise ApprovalAuthError("approval_forbidden_in_agent_role")


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
    ) -> str:
        """Create a durable approval that starts ``pending``."""
        require_orchestrator("record_approval")
        if is_untrusted_agent_role(agent_role_from_env()):
            raise ApprovalAuthError("approval_create_forbidden_in_agent_role")
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
            require_authority=True,
        )

    def approve(
        self,
        *,
        approval_id: str,
        user_session: UserSession,
        expected_job_key: Optional[str] = None,
        expected_session_id: Optional[str] = None,
        expected_fingerprint: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Authenticated user action: pending → approved.
        Agents cannot call this successfully (orchestrator + session required).
        """
        require_orchestrator("approve")
        row = self.ledger.get_approval(approval_id)
        if row is None:
            raise ApprovalAuthError("approval_not_found")
        verify_user_session(user_session, expected_user_id=row["user_id"])
        if row["status"] == "revoked":
            raise ApprovalAuthError("approval_revoked")
        if expected_job_key is not None and row["job_key"] != expected_job_key:
            raise ApprovalAuthError("approval_job_mismatch")
        if expected_session_id is not None and row["session_id"] != expected_session_id:
            raise ApprovalAuthError("approval_session_mismatch")
        if (
            expected_fingerprint is not None
            and row["artifact_fingerprint"] != expected_fingerprint
        ):
            raise ApprovalAuthError("approval_fingerprint_mismatch")
        # Bind decision to authenticated session fingerprint (not agent-supplied).
        meta = dict(row.get("meta") or {})
        meta["auth_method"] = user_session.auth_method
        meta["session_fp"] = user_session.fingerprint()
        self.ledger.decide_approval(
            approval_id=approval_id,
            status="approved",
            decided_by=f"user:{user_session.user_id}",
            meta=meta,
            require_authority=True,
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
        verify_user_session(user_session, expected_user_id=row["user_id"])
        meta = dict(row.get("meta") or {})
        if reason:
            meta["revoke_reason"] = reason
        self.ledger.decide_approval(
            approval_id=approval_id,
            status="revoked",
            decided_by=f"user:{user_session.user_id}",
            meta=meta,
            require_authority=True,
        )
        decided = self.ledger.get_approval(approval_id)
        assert decided is not None
        return decided


def constant_time_token_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
