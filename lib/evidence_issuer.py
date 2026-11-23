#!/usr/bin/env python3
"""
Trusted evidence issuer — isolated from untrusted agent processes.

Agents never hold the HMAC secret and cannot mint evidence without:
1. A live OrchestratorContext (not merely absence of JOBOPS_AGENT_ROLE), and
2. A durable approved ledger row bound to user + requisition + session + fingerprint.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional, Sequence

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from ledger import Ledger  # noqa: E402
from submission_authorize import (  # noqa: E402
    EvidenceSecretError,
    evidence_secret,
    issue_consent_record,
    issue_trusted_evidence,
)
from trust_boundary import (  # noqa: E402
    agent_role_from_env,
    is_untrusted_agent_role,
    require_orchestrator,
)

# Claims that require a durable approved row before minting.
APPROVAL_GATED_CLAIMS = frozenset(
    {
        "user_consent",
        "portal_session",
        "posting_open",
        "not_duplicate",
        "hard_eligibility_met",
        "filenames_correct",
        "required_fields_complete",
        "screening_answers_verified",
        "no_auth_wall",
    }
)


class EvidenceIssuanceError(PermissionError):
    """Raised when issuance is refused (missing approval, agent context, etc.)."""


def _require_issuance_authority() -> None:
    """
    Trusted issuance depends on protected orchestrator state.

    Clearing or forging JOBOPS_AGENT_ROLE is insufficient — a live
    OrchestratorContext with ``issue_evidence`` scope is required.
    """
    role = agent_role_from_env()
    if is_untrusted_agent_role(role):
        raise EvidenceIssuanceError(f"evidence_issuance_forbidden_in_agent_role:{role}")
    try:
        require_orchestrator("issue_evidence")
    except PermissionError as exc:
        raise EvidenceIssuanceError(str(exc)) from exc


class TrustedEvidenceIssuer:
    """
    Mint HMAC evidence only after durable approval lookup + orchestrator authority.
    Secret is loaded from installation-specific storage — never from agent env widen.
    """

    def __init__(
        self,
        ledger: Ledger,
        *,
        workspace_home: Optional[Path] = None,
        secret: Optional[bytes] = None,
    ) -> None:
        _require_issuance_authority()
        self.ledger = ledger
        self.workspace_home = workspace_home
        if secret is not None:
            self._secret = secret
        else:
            self._secret = evidence_secret(workspace_home=workspace_home)

    def issue_claim(
        self,
        *,
        claim: str,
        approval_id: str,
        user_id: str,
        job_key: str,
        session_id: str,
        artifact_fingerprint: str,
        ttl_sec: int = 3600,
    ) -> dict[str, Any]:
        _require_issuance_authority()
        ok, reason, row = self.ledger.require_approved(
            approval_id,
            user_id=user_id,
            job_key=job_key,
            session_id=session_id,
            artifact_fingerprint=artifact_fingerprint,
        )
        if not ok:
            raise EvidenceIssuanceError(f"issuance_blocked:{reason}")
        assert row is not None
        user_id = row["user_id"]
        job_key = row["job_key"]
        session_id = row["session_id"]
        artifact_fingerprint = row["artifact_fingerprint"]
        if claim not in APPROVAL_GATED_CLAIMS and claim != "user_consent":
            pass

        if claim == "user_consent":
            return issue_consent_record(
                user_id=user_id,
                job_key=job_key,
                session_id=session_id,
                artifact_fingerprint=artifact_fingerprint,
                approval_id=approval_id,
                secret=self._secret,
                ttl_sec=ttl_sec,
            )
        return issue_trusted_evidence(
            claim=claim,
            user_id=user_id,
            job_key=job_key,
            session_id=session_id,
            artifact_fingerprint=artifact_fingerprint,
            issuer="jobops.evidence_issuer",
            ttl_sec=ttl_sec,
            secret=self._secret,
        )

    def issue_package(
        self,
        *,
        approval_id: str,
        user_id: str,
        job_key: str,
        session_id: str,
        artifact_fingerprint: str,
        claims: Optional[Sequence[str]] = None,
    ) -> dict[str, Any]:
        """Mint a full evidence package for authorize_submission."""
        claim_list = list(
            claims
            or (
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
        )
        out: dict[str, Any] = {
            "user_id": user_id,
            "session_id": session_id,
            "approval_id": approval_id,
            "issuer": "jobops.evidence_issuer",
        }
        for claim in claim_list:
            out[claim] = self.issue_claim(
                claim=claim,
                approval_id=approval_id,
                user_id=user_id,
                job_key=job_key,
                session_id=session_id,
                artifact_fingerprint=artifact_fingerprint,
            )
        return out


def require_installation_secret(workspace_home: Optional[Path] = None) -> bytes:
    """Public helper — fail closed when no installation secret exists."""
    try:
        return evidence_secret(workspace_home=workspace_home)
    except EvidenceSecretError:
        raise
