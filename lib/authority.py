#!/usr/bin/env python3
"""
Protected control-plane authority issuer.

Untrusted agent processes cannot mint OrchestratorContext privileges by clearing
JOBOPS_AGENT_ROLE or constructing OrchestratorAuthority directly. Authority is
issued only by ControlPlaneController using a workspace-local signing key that
is never placed in agent subprocess environments.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from trust_boundary import (
    agent_role_from_env,
    is_untrusted_agent_role,
)

AUTHORITY_KEY_NAME = "orchestrator_authority.key"
DEFAULT_GRANT_TTL_SEC = 3600
DEFAULT_SCOPES = frozenset(
    {"approve", "issue_evidence", "reserve_submit", "record_approval"}
)
SENSITIVE_AGENT_ROLES = frozenset({"frontier_submit", "outreach"})

_tls = threading.local()


class AuthorityError(PermissionError):
    """Raised when control-plane authority issuance or verification fails."""


@dataclass(frozen=True)
class ControlPlaneSeal:
    """Process-local seal proving bootstrap occurred before agent contamination."""

    seal_id: str
    workspace_home: str
    issued_at: str


@dataclass(frozen=True)
class AuthorityGrant:
    """Verifiable, time-bounded orchestrator privilege grant."""

    grant_id: str
    principal: str
    scopes: frozenset[str]
    issued_at: str
    expires_at: str
    signature: str
    workspace_fingerprint: str

    def permits(self, scope: str) -> bool:
        return scope in self.scopes

    def to_wire(self) -> dict[str, object]:
        return {
            "grant_id": self.grant_id,
            "principal": self.principal,
            "scopes": sorted(self.scopes),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "signature": self.signature,
            "workspace_fingerprint": self.workspace_fingerprint,
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def authority_key_path(workspace_home: Path) -> Path:
    return Path(workspace_home).expanduser().resolve() / "secrets" / AUTHORITY_KEY_NAME


def workspace_fingerprint(workspace_home: Path) -> str:
    resolved = str(Path(workspace_home).expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:32]


def _chmod_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _chmod_private_file(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _assert_private_file(path: Path) -> None:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise AuthorityError(f"authority_key_unreadable:{exc}") from exc
    if mode & 0o077:
        raise AuthorityError(f"authority_key_insecure_mode:{oct(mode)}")


def load_or_create_authority_key(workspace_home: Path) -> bytes:
    """Load the control-plane signing key; create mode-0600 if missing."""
    home = Path(workspace_home).expanduser().resolve()
    secrets_dir = home / "secrets"
    _chmod_private_dir(secrets_dir)
    _chmod_private_dir(home / "state")
    path = authority_key_path(home)
    if not path.is_file():
        key = secrets.token_bytes(32)
        path.write_bytes(key)
        _chmod_private_file(path)
        return key
    _assert_private_file(path)
    key = path.read_bytes()
    if len(key) < 16:
        raise AuthorityError("authority_key_too_short")
    return key


def _signing_payload(
    *,
    grant_id: str,
    principal: str,
    scopes: Iterable[str],
    issued_at: str,
    expires_at: str,
    workspace_fp: str,
) -> bytes:
    body = {
        "grant_id": grant_id,
        "principal": principal,
        "scopes": sorted(scopes),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "workspace_fingerprint": workspace_fp,
    }
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _sign(secret: bytes, payload: bytes) -> str:
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _contamination_flag() -> bool:
    return bool(getattr(_tls, "agent_contaminated", False))


def mark_agent_contaminated(reason: str = "agent_role") -> None:
    """Poison control-plane bootstrap for the remainder of this process."""
    _tls.agent_contaminated = True
    _tls.contamination_reason = reason
    _tls.control_plane_seal = None


def note_agent_role(role: str) -> None:
    if is_untrusted_agent_role(role):
        mark_agent_contaminated(f"agent_role:{role}")


def current_control_plane_seal() -> Optional[ControlPlaneSeal]:
    return getattr(_tls, "control_plane_seal", None)


def control_plane_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    env = environ if environ is not None else os.environ
    return (env.get("JOBOPS_CONTROL_PLANE") or "0") == "1"


def require_control_plane_enabled() -> None:
    """
    Agents never receive JOBOPS_CONTROL_PLANE=1. Clearing JOBOPS_AGENT_ROLE
    does not enable the control plane.
    """
    role = agent_role_from_env()
    if is_untrusted_agent_role(role):
        mark_agent_contaminated(f"agent_role:{role}")
        raise AuthorityError(f"control_plane_forbidden_in_agent_role:{role}")
    if _contamination_flag():
        reason = getattr(_tls, "contamination_reason", "contaminated")
        raise AuthorityError(f"control_plane_forbidden_after_agent_contamination:{reason}")
    if not control_plane_enabled():
        raise AuthorityError("control_plane_not_enabled")


def bootstrap_control_plane(workspace_home: Path | str) -> ControlPlaneSeal:
    """
    Enter the protected control plane for this process.

    Requires JOBOPS_CONTROL_PLANE=1 and refuses agent roles / contamination
    (clearing JOBOPS_AGENT_ROLE does not enable the control plane).
    """
    require_control_plane_enabled()
    home = Path(workspace_home).expanduser().resolve()
    load_or_create_authority_key(home)
    seal = ControlPlaneSeal(
        seal_id=secrets.token_hex(16),
        workspace_home=str(home),
        issued_at=_iso(_utc_now()),
    )
    _tls.control_plane_seal = seal
    return seal


def reset_control_plane_for_tests() -> None:
    """Test-only: clear contamination/seal so fixtures can re-bootstrap."""
    _tls.agent_contaminated = False
    _tls.contamination_reason = ""
    _tls.control_plane_seal = None


class ControlPlaneController:
    """
    Sole sanctioned issuer of orchestrator authority grants.

    Application code cannot grant itself approval/evidence/submit scopes without
    a live control-plane seal and the workspace authority key.
    """

    def __init__(
        self,
        workspace_home: Path | str,
        seal: Optional[ControlPlaneSeal] = None,
    ) -> None:
        require_control_plane_enabled()
        home = Path(workspace_home).expanduser().resolve()
        active = seal or current_control_plane_seal()
        if active is None:
            raise AuthorityError("control_plane_seal_required")
        if Path(active.workspace_home).resolve() != home:
            raise AuthorityError("control_plane_seal_workspace_mismatch")
        self.workspace_home = home
        self.seal = active
        self._secret = load_or_create_authority_key(home)

    def issue_grant(
        self,
        *,
        principal: str,
        scopes: Optional[Sequence[str]] = None,
        ttl_sec: int = DEFAULT_GRANT_TTL_SEC,
    ) -> AuthorityGrant:
        if not principal or not str(principal).strip():
            raise AuthorityError("authority_principal_required")
        if is_untrusted_agent_role(agent_role_from_env()) or _contamination_flag():
            raise AuthorityError("authority_issue_forbidden_in_agent_context")
        scope_set = frozenset(scopes) if scopes is not None else DEFAULT_SCOPES
        unknown = scope_set - DEFAULT_SCOPES
        if unknown:
            raise AuthorityError(f"authority_unknown_scopes:{','.join(sorted(unknown))}")
        if not scope_set:
            raise AuthorityError("authority_scopes_required")
        now = _utc_now()
        issued_at = _iso(now)
        expires_at = _iso(now + timedelta(seconds=max(1, int(ttl_sec))))
        grant_id = f"grant_{secrets.token_hex(16)}"
        ws_fp = workspace_fingerprint(self.workspace_home)
        payload = _signing_payload(
            grant_id=grant_id,
            principal=str(principal).strip(),
            scopes=scope_set,
            issued_at=issued_at,
            expires_at=expires_at,
            workspace_fp=ws_fp,
        )
        return AuthorityGrant(
            grant_id=grant_id,
            principal=str(principal).strip(),
            scopes=scope_set,
            issued_at=issued_at,
            expires_at=expires_at,
            signature=_sign(self._secret, payload),
            workspace_fingerprint=ws_fp,
        )


def verify_authority_grant(
    grant: AuthorityGrant,
    *,
    workspace_home: Path | str,
    required_scope: Optional[str] = None,
) -> AuthorityGrant:
    """Verify signature, workspace binding, expiry, and optional scope."""
    if is_untrusted_agent_role(agent_role_from_env()):
        raise AuthorityError("authority_verify_forbidden_in_agent_role")
    home = Path(workspace_home).expanduser().resolve()
    secret = load_or_create_authority_key(home)
    ws_fp = workspace_fingerprint(home)
    if grant.workspace_fingerprint != ws_fp:
        raise AuthorityError("authority_workspace_mismatch")
    payload = _signing_payload(
        grant_id=grant.grant_id,
        principal=grant.principal,
        scopes=grant.scopes,
        issued_at=grant.issued_at,
        expires_at=grant.expires_at,
        workspace_fp=grant.workspace_fingerprint,
    )
    expected = _sign(secret, payload)
    if not hmac.compare_digest(expected, grant.signature):
        raise AuthorityError("authority_signature_invalid")
    now = _utc_now()
    try:
        expires = _parse_iso(grant.expires_at)
        issued = _parse_iso(grant.issued_at)
    except ValueError as exc:
        raise AuthorityError("authority_timestamp_invalid") from exc
    if expires <= now:
        raise AuthorityError("authority_grant_expired")
    if issued > now + timedelta(seconds=30):
        raise AuthorityError("authority_grant_not_yet_valid")
    if required_scope and not grant.permits(required_scope):
        raise AuthorityError(f"authority_scope_denied:{required_scope}")
    return grant


def issue_test_grant(
    workspace_home: Path | str,
    *,
    principal: str = "pytest",
    scopes: Optional[Sequence[str]] = None,
    ttl_sec: int = DEFAULT_GRANT_TTL_SEC,
) -> AuthorityGrant:
    """
    Test/CLI helper: bootstrap (if needed) and issue a grant.

    Still refuses agent roles and contaminated processes.
    """
    home = Path(workspace_home).expanduser().resolve()
    seal = current_control_plane_seal()
    if seal is None or Path(seal.workspace_home).resolve() != home:
        seal = bootstrap_control_plane(home)
    return ControlPlaneController(home, seal).issue_grant(
        principal=principal,
        scopes=scopes,
        ttl_sec=ttl_sec,
    )
