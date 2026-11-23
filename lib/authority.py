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
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from trust_boundary import (
    agent_role_from_env,
    is_untrusted_agent_role,
)

AUTHORITY_KEY_NAME = "orchestrator_authority.key"
PRIVILEGE_NAME = "control_plane.privilege"
CONFIRMATION_KEY_NAME = "confirmation_hmac.key"
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


def privilege_path(workspace_home: Path) -> Path:
    return Path(workspace_home).expanduser().resolve() / "secrets" / PRIVILEGE_NAME


def confirmation_key_path(workspace_home: Path) -> Path:
    return (
        Path(workspace_home).expanduser().resolve() / "secrets" / CONFIRMATION_KEY_NAME
    )


def approvals_storage_path(workspace_home: Path) -> Path:
    """Durable approval / session DB directory — must stay mode 0700."""
    return Path(workspace_home).expanduser().resolve() / "state"


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


def _assert_private_dir(path: Path) -> None:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise AuthorityError(f"control_plane_storage_unreadable:{exc}") from exc
    if mode & 0o077:
        raise AuthorityError(f"control_plane_storage_insecure_mode:{oct(mode)}")


def install_control_plane_privilege(workspace_home: Path | str) -> Path:
    """
    Installer/CLI path: create the OS-permission-gated privilege credential.

    ``JOBOPS_CONTROL_PLANE=1`` alone is not enough to bootstrap — this file must
    exist and be openable by the process. Agent subprocesses never receive
    ``JOBOPS_HOME``, so they cannot install or open it.
    """
    require_control_plane_enabled()
    home = Path(workspace_home).expanduser().resolve()
    secrets_dir = home / "secrets"
    state_dir = approvals_storage_path(home)
    _chmod_private_dir(secrets_dir)
    _chmod_private_dir(state_dir)
    path = privilege_path(home)
    if not path.is_file():
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, secrets.token_bytes(32))
        finally:
            os.close(fd)
        _chmod_private_file(path)
    else:
        _assert_private_file(path)
    # Prove OS-level open succeeds for this process.
    try:
        fd = os.open(str(path), os.O_RDONLY)
        os.close(fd)
    except OSError as exc:
        raise AuthorityError(f"control_plane_privilege_denied:{exc}") from exc
    return path


def require_privileged_access(workspace_home: Path | str) -> Path:
    """
    Enforce OS permission boundary for control-plane secrets.

    Rejects when the privilege credential is missing or unreadable — setting
    ``JOBOPS_CONTROL_PLANE=1`` without privileged filesystem access fails closed.
    """
    require_control_plane_enabled()
    home = Path(workspace_home).expanduser().resolve()
    path = privilege_path(home)
    if not path.is_file():
        raise AuthorityError("control_plane_privilege_missing")
    _assert_private_file(path)
    state_dir = approvals_storage_path(home)
    if state_dir.is_dir():
        _assert_private_dir(state_dir)
    try:
        fd = os.open(str(path), os.O_RDONLY)
        os.close(fd)
    except OSError as exc:
        raise AuthorityError(f"control_plane_privilege_denied:{exc}") from exc
    return path


def _load_or_create_secret_file(path: Path, *, too_short_code: str) -> bytes:
    """Create a mode-0600 secret file or load an existing one (re-chmod on race)."""
    if not path.is_file():
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                key = secrets.token_bytes(32)
                os.write(fd, key)
            finally:
                os.close(fd)
            _chmod_private_file(path)
            return key
        except FileExistsError:
            # Lost create race — fall through to load path.
            pass
    # Repair insecure mode from concurrent writers / umask races, then assert.
    # Brief retry covers readers that observe a partially-written create.
    last: bytes = b""
    for attempt in range(8):
        _chmod_private_file(path)
        _assert_private_file(path)
        last = path.read_bytes()
        if len(last) >= 16:
            return last
        time.sleep(0.005 * (attempt + 1))
    raise AuthorityError(too_short_code)


def load_or_create_authority_key(workspace_home: Path) -> bytes:
    """Load the control-plane signing key; create mode-0600 if missing."""
    home = Path(workspace_home).expanduser().resolve()
    require_privileged_access(home)
    secrets_dir = home / "secrets"
    _chmod_private_dir(secrets_dir)
    _chmod_private_dir(approvals_storage_path(home))
    return _load_or_create_secret_file(
        authority_key_path(home),
        too_short_code="authority_key_too_short",
    )


def load_or_create_confirmation_key(workspace_home: Path) -> bytes:
    """HMAC key for interactive confirmation receipts (privilege-gated)."""
    home = Path(workspace_home).expanduser().resolve()
    require_privileged_access(home)
    secrets_dir = home / "secrets"
    _chmod_private_dir(secrets_dir)
    return _load_or_create_secret_file(
        confirmation_key_path(home),
        too_short_code="confirmation_key_too_short",
    )


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

    Requires:
    - ``JOBOPS_CONTROL_PLANE=1`` (never sufficient alone)
    - OS-openable ``secrets/control_plane.privilege`` (mode 0600)
    - Non-agent / non-contaminated process

    Clearing ``JOBOPS_AGENT_ROLE`` does not enable the control plane.
    """
    require_control_plane_enabled()
    home = Path(workspace_home).expanduser().resolve()
    require_privileged_access(home)
    load_or_create_authority_key(home)
    load_or_create_confirmation_key(home)
    seal = ControlPlaneSeal(
        seal_id=secrets.token_hex(16),
        workspace_home=str(home),
        issued_at=_iso(_utc_now()),
    )
    _tls.control_plane_seal = seal
    return seal


def reset_control_plane_for_tests() -> None:
    """
    Test-only: clear contamination/seal so fixtures can re-bootstrap.

    Forbidden in production CLI paths. Requires **both** ``PYTEST_CURRENT_TEST``
    (pytest harness) and ``JOBOPS_ALLOW_TEST_CONTROL_PLANE_RESET=1``. The env
    flag alone never unlocks production. Never clears ``JOBOPS_AGENT_ROLE`` and
    never installs privilege credentials.
    """
    allowed = (
        "PYTEST_CURRENT_TEST" in os.environ
        and (os.environ.get("JOBOPS_ALLOW_TEST_CONTROL_PLANE_RESET") or "0") == "1"
    )
    if not allowed:
        raise AuthorityError("control_plane_reset_forbidden_outside_tests")
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
        # Privilege credential before seal — env flag alone must fail closed.
        require_privileged_access(home)
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


def issue_orchestrator_grant(
    workspace_home: Path | str,
    *,
    principal: str = "orchestrator",
    scopes: Optional[Sequence[str]] = None,
    ttl_sec: int = DEFAULT_GRANT_TTL_SEC,
) -> AuthorityGrant:
    """
    Production path: issue a grant only when privilege credentials already exist.

    Never installs ``control_plane.privilege``. Callers (including ``jobops approve``)
    must provision via ``jobops control-plane provision`` / ``install_control_plane_privilege``
    beforehand. Still refuses agent roles and contaminated processes.
    """
    home = Path(workspace_home).expanduser().resolve()
    require_privileged_access(home)
    seal = current_control_plane_seal()
    if seal is None or Path(seal.workspace_home).resolve() != home:
        seal = bootstrap_control_plane(home)
    return ControlPlaneController(home, seal).issue_grant(
        principal=principal,
        scopes=scopes,
        ttl_sec=ttl_sec,
    )


def issue_test_grant(
    workspace_home: Path | str,
    *,
    principal: str = "pytest",
    scopes: Optional[Sequence[str]] = None,
    ttl_sec: int = DEFAULT_GRANT_TTL_SEC,
) -> AuthorityGrant:
    """
    Test/provision helper: may install privilege credential, then issue a grant.

    Production approval must use ``issue_orchestrator_grant`` instead. Still refuses
    agent roles and contaminated processes. ``bootstrap_control_plane`` itself never
    auto-creates the privilege file — only this helper / ``jobops control-plane
    provision`` / ``install_control_plane_privilege`` may install it.
    ``jobops init`` never installs privilege.
    """
    home = Path(workspace_home).expanduser().resolve()
    install_control_plane_privilege(home)
    return issue_orchestrator_grant(
        home,
        principal=principal,
        scopes=scopes,
        ttl_sec=ttl_sec,
    )
