#!/usr/bin/env python3
"""
Authenticated approval controller.

New approvals always start as ``pending``. Only an authenticated interactive
confirmation (InteractiveApprovalGate) may mint a stored, single-use session
bound to a specific pending approval. Caller-controlled booleans are not proof
of user intent. Arbitrary user IDs, fabricated confirmations/tokens, expired
sessions, and replayed approvals are rejected.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from authority import (  # noqa: E402
    AuthorityError,
    load_or_create_confirmation_key,
    require_privileged_access,
)
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
class ConfirmationPrompt:
    """Exact approval details presented to the authenticated principal."""

    approval_id: str
    user_id: str
    job_key: str
    artifact_fingerprint: str
    action: str
    challenge: str
    document_path: str = ""

    def render(self) -> str:
        return (
            "jobsOps approval confirmation\n"
            f"  principal : {self.user_id}\n"
            f"  approval  : {self.approval_id}\n"
            f"  job       : {self.job_key}\n"
            f"  fingerprint: {self.artifact_fingerprint}\n"
            f"  document  : {self.document_path or '(none)'}\n"
            f"  action    : {self.action}\n"
            f"  challenge : {self.challenge}\n"
            "Type the challenge exactly to confirm. Anything else cancels.\n"
        )


@dataclass(frozen=True)
class ConfirmationReceipt:
    """
    Cryptographic proof that InteractiveApprovalGate obtained a real confirmation.

    Constructing this dataclass with invented fields fails MAC verification —
    model-controlled code cannot mint a valid receipt without the privilege-gated
    confirmation key and a successful interactive challenge echo.
    """

    receipt_id: str
    approval_id: str
    user_id: str
    job_key: str
    artifact_fingerprint: str
    action: str
    challenge: str
    confirmed_at: str
    mac: str

    def payload(self) -> bytes:
        body = {
            "receipt_id": self.receipt_id,
            "approval_id": self.approval_id,
            "user_id": self.user_id,
            "job_key": self.job_key,
            "artifact_fingerprint": self.artifact_fingerprint,
            "action": self.action,
            "challenge": self.challenge,
            "confirmed_at": self.confirmed_at,
        }
        return json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")


class ConfirmationChannel(Protocol):
    """Interactive channel that presents the prompt and returns the user's echo."""

    def present_and_confirm(self, prompt: ConfirmationPrompt) -> str: ...


class TtyConfirmationChannel:
    """
    Sole production-trusted interactive confirmation channel.

    Trust is by exact type identity (``type(channel) is TtyConfirmationChannel``),
    not by forgeable attributes. Subclasses and arbitrary objects that set
    ``_jobops_trusted_interactive`` (or any other marker) never qualify.
    """

    def present_and_confirm(self, prompt: ConfirmationPrompt) -> str:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ApprovalAuthError("interactive_tty_required")
        sys.stdout.write(prompt.render())
        sys.stdout.flush()
        try:
            return sys.stdin.readline().strip()
        except EOFError as exc:
            raise ApprovalAuthError("interactive_confirmation_aborted") from exc


def _is_production_confirmation_channel(channel: object) -> bool:
    """Exact-type gate — attribute markers and subclasses are not trusted."""
    return type(channel) is TtyConfirmationChannel


def _authorize_test_confirmation_channel(workspace_home: Path) -> None:
    """
    Allow non-TTY confirmation channels only under authenticated pytest config.

    Requires **both** ``PYTEST_CURRENT_TEST`` (pytest harness) and
    ``JOBOPS_ALLOW_TEST_CONFIRMATION=1``, plus a pre-existing privilege
    credential and a non-agent process. The env flag alone never unlocks
    production authorization.
    """
    import os

    if "PYTEST_CURRENT_TEST" not in os.environ:
        raise ApprovalAuthError("confirmation_channel_substitution_forbidden")
    if (os.environ.get("JOBOPS_ALLOW_TEST_CONFIRMATION") or "0") != "1":
        raise ApprovalAuthError("confirmation_channel_substitution_forbidden")
    if is_untrusted_agent_role(agent_role_from_env()):
        raise ApprovalAuthError("confirmation_channel_forbidden_in_agent_role")
    try:
        require_privileged_access(workspace_home)
    except AuthorityError as exc:
        raise ApprovalAuthError(
            f"confirmation_channel_privilege_denied:{exc}"
        ) from exc


def resolve_confirmation_channel(
    channel: Optional[ConfirmationChannel],
    *,
    workspace_home: Path | str,
) -> ConfirmationChannel:
    """
    Production default is the concrete TTY channel type.

    Synthetic / echo / attribute-forged channels require authenticated pytest
    test config — never qualify via forgeable markers.
    """
    home = Path(workspace_home).expanduser().resolve()
    if channel is None:
        return TtyConfirmationChannel()
    if _is_production_confirmation_channel(channel):
        return channel
    _authorize_test_confirmation_channel(home)
    return channel


@dataclass(frozen=True)
class UserSession:
    """
    Authenticated end-user session for approval decisions.

    Constructing this dataclass alone is insufficient — verify/consume requires
    a matching stored row issued by SessionIssuer after interactive confirmation.
    """

    user_id: str
    session_token: str
    session_id: str
    approval_id: str
    auth_method: str = "interactive_confirm"
    expires_at: str = ""
    confirmation_receipt_id: str = ""

    def fingerprint(self) -> str:
        return hashlib.sha256(
            f"{self.user_id}|{self.auth_method}|{self.session_id}|{self.approval_id}|{self.session_token}".encode(
                "utf-8"
            )
        ).hexdigest()


def _sign_receipt(secret: bytes, receipt: ConfirmationReceipt) -> str:
    return hmac.new(secret, receipt.payload(), hashlib.sha256).hexdigest()


def verify_confirmation_receipt(
    receipt: ConfirmationReceipt,
    *,
    workspace_home: Path | str,
    expected_approval_id: str,
    expected_user_id: str,
    expected_job_key: str,
    expected_fingerprint: str,
    expected_action: str = "approve",
) -> None:
    """Reject fabricated or mismatched confirmation receipts."""
    try:
        secret = load_or_create_confirmation_key(Path(workspace_home))
    except AuthorityError as exc:
        raise ApprovalAuthError(f"confirmation_key_unavailable:{exc}") from exc
    expected_mac = _sign_receipt(secret, receipt)
    if not hmac.compare_digest(expected_mac, receipt.mac):
        raise ApprovalAuthError("confirmation_receipt_mac_invalid")
    if receipt.approval_id != expected_approval_id:
        raise ApprovalAuthError("confirmation_approval_mismatch")
    if receipt.user_id != expected_user_id:
        raise ApprovalAuthError("confirmation_principal_mismatch")
    if receipt.job_key != expected_job_key:
        raise ApprovalAuthError("confirmation_job_mismatch")
    if receipt.artifact_fingerprint != expected_fingerprint:
        raise ApprovalAuthError("confirmation_fingerprint_mismatch")
    if receipt.action != expected_action:
        raise ApprovalAuthError("confirmation_action_mismatch")
    if not receipt.challenge or len(receipt.challenge) < 16:
        raise ApprovalAuthError("confirmation_challenge_invalid")


class InteractiveApprovalGate:
    """
    Trusted interactive approval entry point.

    Verifies the authenticated principal, presents the exact job / fingerprint /
    action, requires a real challenge echo that model-controlled code cannot
    fabricate, and binds the resulting session to that approval.
    """

    def __init__(
        self,
        ledger: Ledger,
        workspace_home: Path | str,
        *,
        channel: Optional[ConfirmationChannel] = None,
    ) -> None:
        require_orchestrator("approve")
        if is_untrusted_agent_role(agent_role_from_env()):
            raise ApprovalAuthError("interactive_gate_forbidden_in_agent_role")
        home = Path(workspace_home).expanduser().resolve()
        try:
            require_privileged_access(home)
        except AuthorityError as exc:
            raise ApprovalAuthError(f"interactive_gate_privilege_denied:{exc}") from exc
        self.ledger = ledger
        self.workspace_home = home
        self.channel: ConfirmationChannel = resolve_confirmation_channel(
            channel, workspace_home=home
        )
        self._secret = load_or_create_confirmation_key(home)

    def confirm_and_issue_session(
        self,
        *,
        approval_id: str,
        principal: str,
        action: str = "approve",
        ttl_sec: int = DEFAULT_SESSION_TTL_SEC,
        auth_method: str = "interactive_confirm",
    ) -> UserSession:
        require_orchestrator("approve")
        if is_untrusted_agent_role(agent_role_from_env()):
            raise ApprovalAuthError("user_session_forbidden_in_agent_role")
        if not principal or not str(principal).strip():
            raise ApprovalAuthError("principal_required")
        uid = str(principal).strip()
        if uid in {"*", "any", "admin", "root"} or uid.startswith("arbitrary:"):
            raise ApprovalAuthError("user_id_rejected")
        row = self.ledger.get_approval(approval_id)
        if row is None:
            raise ApprovalAuthError("approval_not_found")
        if row["user_id"] != uid:
            raise ApprovalAuthError("confirmation_principal_mismatch")
        if action == "approve" and row["status"] != "pending":
            raise ApprovalAuthError(f"approval_not_pending:{row['status']}")
        if action == "revoke" and row["status"] not in {"pending", "approved"}:
            raise ApprovalAuthError(f"approval_not_revocable:{row['status']}")
        if action not in {"approve", "revoke"}:
            raise ApprovalAuthError(f"unsupported_session_action:{action}")

        challenge = secrets.token_hex(16)
        prompt = ConfirmationPrompt(
            approval_id=approval_id,
            user_id=uid,
            job_key=str(row["job_key"]),
            artifact_fingerprint=str(row["artifact_fingerprint"]),
            action=action,
            challenge=challenge,
            document_path=str(row.get("document_path") or ""),
        )
        response = self.channel.present_and_confirm(prompt)
        if not hmac.compare_digest(str(response).strip(), challenge):
            raise ApprovalAuthError("confirmation_challenge_mismatch")

        now = _utc_now()
        receipt = ConfirmationReceipt(
            receipt_id=f"crec_{secrets.token_hex(16)}",
            approval_id=approval_id,
            user_id=uid,
            job_key=str(row["job_key"]),
            artifact_fingerprint=str(row["artifact_fingerprint"]),
            action=action,
            challenge=challenge,
            confirmed_at=_iso(now),
            mac="",  # filled after
        )
        mac = _sign_receipt(self._secret, receipt)
        receipt = ConfirmationReceipt(
            receipt_id=receipt.receipt_id,
            approval_id=receipt.approval_id,
            user_id=receipt.user_id,
            job_key=receipt.job_key,
            artifact_fingerprint=receipt.artifact_fingerprint,
            action=receipt.action,
            challenge=receipt.challenge,
            confirmed_at=receipt.confirmed_at,
            mac=mac,
        )
        self.ledger.store_confirmation_receipt(
            receipt_id=receipt.receipt_id,
            approval_id=approval_id,
            user_id=uid,
            challenge_hash=_token_hash(challenge),
            action=action,
            confirmed_at=receipt.confirmed_at,
            mac=mac,
            meta={
                "job_key": receipt.job_key,
                "artifact_fingerprint": receipt.artifact_fingerprint,
            },
        )
        return SessionIssuer(self.ledger, self.workspace_home).issue_for_approval(
            user_id=uid,
            approval_id=approval_id,
            confirmation=receipt,
            auth_method=auth_method,
            ttl_sec=ttl_sec,
            action_name=action,
        )


class SessionIssuer:
    """Trusted issuer of stored, approval-bound, single-use user sessions."""

    def __init__(self, ledger: Ledger, workspace_home: Path | str) -> None:
        require_orchestrator("approve")
        if is_untrusted_agent_role(agent_role_from_env()):
            raise ApprovalAuthError("session_issuer_forbidden_in_agent_role")
        home = Path(workspace_home).expanduser().resolve()
        try:
            require_privileged_access(home)
        except AuthorityError as exc:
            raise ApprovalAuthError(f"session_issuer_privilege_denied:{exc}") from exc
        self.ledger = ledger
        self.workspace_home = home

    def issue_for_approval(
        self,
        *,
        user_id: str,
        approval_id: str,
        confirmation: ConfirmationReceipt,
        auth_method: str = "interactive_confirm",
        ttl_sec: int = DEFAULT_SESSION_TTL_SEC,
        action_name: str = "approve",
    ) -> UserSession:
        """
        Mint a session bound to a pending approval after interactive confirmation.

        A valid ``ConfirmationReceipt`` from InteractiveApprovalGate is required —
        a caller-controlled boolean is not accepted as proof of user intent.
        """
        require_orchestrator("approve")
        if is_untrusted_agent_role(agent_role_from_env()):
            raise ApprovalAuthError("user_session_forbidden_in_agent_role")
        if confirmation is None:
            raise ApprovalAuthError("confirmation_receipt_required")
        if not user_id or not str(user_id).strip():
            raise ApprovalAuthError("user_id_required")
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
        verify_confirmation_receipt(
            confirmation,
            workspace_home=self.workspace_home,
            expected_approval_id=approval_id,
            expected_user_id=uid,
            expected_job_key=str(row["job_key"]),
            expected_fingerprint=str(row["artifact_fingerprint"]),
            expected_action=action_name,
        )
        stored_receipt = self.ledger.get_confirmation_receipt(confirmation.receipt_id)
        if stored_receipt is None:
            raise ApprovalAuthError("confirmation_receipt_not_found")
        if stored_receipt.get("consumed_at"):
            raise ApprovalAuthError("confirmation_receipt_already_consumed")
        if stored_receipt["approval_id"] != approval_id:
            raise ApprovalAuthError("confirmation_approval_mismatch")
        if stored_receipt["user_id"] != uid:
            raise ApprovalAuthError("confirmation_principal_mismatch")
        # Consume confirmation (single-use) then issue session.
        if not self.ledger.consume_confirmation_receipt(confirmation.receipt_id):
            raise ApprovalAuthError("confirmation_receipt_consume_failed")
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
            meta={"confirmation_receipt_id": confirmation.receipt_id},
        )
        return UserSession(
            user_id=uid,
            session_token=token,
            session_id=session_id,
            approval_id=approval_id,
            auth_method=auth_method,
            expires_at=expires_at,
            confirmation_receipt_id=confirmation.receipt_id,
        )


def issue_confirmed_session(
    *,
    ledger: Ledger,
    workspace_home: Path | str,
    user_id: str,
    approval_id: str,
    channel: Optional[ConfirmationChannel] = None,
    action: str = "approve",
    ttl_sec: int = DEFAULT_SESSION_TTL_SEC,
) -> UserSession:
    """
    Preferred entry: interactive gate → confirmation receipt → stored session.

    Default channel is TTY. Synthetic echo channels are refused unless an
    authenticated pytest configuration is active (``PYTEST_CURRENT_TEST`` +
    ``JOBOPS_ALLOW_TEST_CONFIRMATION=1`` + privilege). Attribute markers never
    qualify. Model-controlled code cannot mint a valid echo without the gate.
    """
    gate = InteractiveApprovalGate(
        ledger,
        workspace_home,
        channel=channel,
    )
    return gate.confirm_and_issue_session(
        approval_id=approval_id,
        principal=user_id,
        action=action,
        ttl_sec=ttl_sec,
    )


def mint_user_session(
    user_id: str,
    *,
    approval_id: str,
    ledger: Ledger,
    workspace_home: Path | str,
    confirmation: Optional[ConfirmationReceipt] = None,
    channel: Optional[ConfirmationChannel] = None,
    auth_method: str = "interactive_confirm",
    ttl_sec: int = DEFAULT_SESSION_TTL_SEC,
    **kwargs: Any,
) -> UserSession:
    """
    Create a fresh stored session bound to a pending approval (orchestrator only).

    Requires interactive confirmation. Legacy ``explicit_user_action=True`` is
    rejected — it is not proof of user intent.
    """
    if "explicit_user_action" in kwargs:
        # Caller-controlled boolean is no longer accepted as authorization proof.
        if kwargs.get("explicit_user_action") is True and confirmation is None:
            raise ApprovalAuthError(
                "explicit_user_action_not_accepted:use_interactive_confirmation"
            )
        if kwargs.get("explicit_user_action") is False:
            raise ApprovalAuthError("confirmation_receipt_required")
    if confirmation is not None:
        return SessionIssuer(ledger, workspace_home).issue_for_approval(
            user_id=user_id,
            approval_id=approval_id,
            confirmation=confirmation,
            auth_method=auth_method,
            ttl_sec=ttl_sec,
        )
    if channel is None:
        raise ApprovalAuthError(
            "confirmation_channel_or_receipt_required:"
            "pass InteractiveApprovalGate / TtyConfirmationChannel / ConfirmationReceipt"
        )
    return issue_confirmed_session(
        ledger=ledger,
        workspace_home=workspace_home,
        user_id=user_id,
        approval_id=approval_id,
        channel=channel,
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

    Prefer ApprovalController.approve which performs binding + consume + decide
    atomically.
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

    def __init__(self, ledger: Ledger, workspace_home: Path | str | None = None) -> None:
        require_orchestrator("record_approval")
        self.ledger = ledger
        self.workspace_home = (
            Path(workspace_home).expanduser().resolve() if workspace_home else None
        )

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

    def interactive_approve(
        self,
        *,
        approval_id: str,
        principal: str,
        expected_job_key: str,
        expected_session_id: str,
        expected_fingerprint: str,
        channel: Optional[ConfirmationChannel] = None,
        workspace_home: Path | str | None = None,
    ) -> dict[str, Any]:
        """Full trusted path: interactive confirm → session → atomic approve."""
        home = workspace_home or self.workspace_home
        if home is None:
            raise ApprovalAuthError("workspace_home_required")
        # resolve_confirmation_channel runs inside InteractiveApprovalGate —
        # synthetic channels cannot substitute into production without test auth.
        session = issue_confirmed_session(
            ledger=self.ledger,
            workspace_home=home,
            user_id=principal,
            approval_id=approval_id,
            channel=channel,
        )
        return self.approve(
            approval_id=approval_id,
            user_session=session,
            expected_job_key=expected_job_key,
            expected_session_id=expected_session_id,
            expected_fingerprint=expected_fingerprint,
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

        Binding validation, session consumption, and approval transition are
        performed atomically in a single ledger transaction.
        """
        require_orchestrator("approve")
        try:
            decided = self.ledger.atomic_approve_with_session(
                approval_id=approval_id,
                user_id=user_session.user_id,
                session_id=user_session.session_id,
                session_token=user_session.session_token,
                expected_job_key=expected_job_key,
                expected_session_id=expected_session_id,
                expected_fingerprint=expected_fingerprint,
                auth_method=user_session.auth_method,
                session_fp=user_session.fingerprint(),
                confirmation_receipt_id=user_session.confirmation_receipt_id,
            )
        except KeyError as exc:
            raise ApprovalAuthError(str(exc)) from exc
        except PermissionError as exc:
            raise ApprovalAuthError(str(exc)) from exc
        return decided

    def revoke(
        self,
        *,
        approval_id: str,
        user_session: UserSession,
        reason: str = "",
    ) -> dict[str, Any]:
        require_orchestrator("approve")
        try:
            decided = self.ledger.atomic_revoke_with_session(
                approval_id=approval_id,
                user_id=user_session.user_id,
                session_id=user_session.session_id,
                session_token=user_session.session_token,
                reason=reason,
                auth_method=user_session.auth_method,
                session_fp=user_session.fingerprint(),
            )
        except KeyError as exc:
            raise ApprovalAuthError(str(exc)) from exc
        except PermissionError as exc:
            raise ApprovalAuthError(str(exc)) from exc
        return decided


def constant_time_token_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
