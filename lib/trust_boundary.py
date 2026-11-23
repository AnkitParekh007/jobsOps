#!/usr/bin/env python3
"""
Trust-boundary primitives for jobsOps.

Untrusted agent processes must never inherit evidence-signing keys, approval
credentials, or private connector tokens. Trusted issuance/approval runs only
inside an explicit OrchestratorContext backed by a ControlPlaneController grant —
clearing JOBOPS_AGENT_ROLE is not enough and cannot mint authority.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Mapping, MutableMapping, Optional, Sequence

if TYPE_CHECKING:
    from authority import AuthorityGrant

# Never copy these into agent child environments (exact names + prefixes).
SECRET_ENV_EXACT = frozenset(
    {
        "JOBOPS_EVIDENCE_SECRET",
        "JOBOPS_CAPABILITY_TOKEN",
        "JOBOPS_APPROVAL_TOKEN",
        "JOBOPS_ORCHESTRATOR_TOKEN",
        "JOBOPS_ISSUANCE_AUTHORITY",
        "JOBOPS_CONTROL_PLANE_TOKEN",
        "JOBOPS_CONTROL_PLANE",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CURSOR_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_SECRET",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "BROWSER_USE_API_KEY",
    }
)

SECRET_ENV_PREFIXES = (
    "JOBOPS_SECRET_",
    "JOBOPS_TOKEN_",
    "JOBOPS_CONNECTOR_",
    "JOBOPS_APPROVAL_",
    "JOBOPS_HMAC_",
    "JOBOPS_AUTHORITY_",
)

# Safe baseline for agent subprocesses (plus explicitly allowlisted extras).
# Intentionally omits JOBOPS_HOME / PYTHONPATH so agents cannot reach the
# control-plane authority key or import privileged issuers via inherited paths.
_AGENT_ENV_BASE_ALLOW = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TMPDIR",
        "TMP",
        "TEMP",
        "TZ",
        "VIRTUAL_ENV",
        "JOBOPS_RUNTIME",
        "JOBOPS_POLICY_VERSION",
        "JOBOPS_ALLOW_SUBMIT",
        "JOBOPS_ENABLE_LIVE_SUBMIT",
        "JOBOPS_ALLOW_FIXTURE_EVIDENCE",
        "JOBOPS_ALLOW_UNSANDBOXED_AGENT",
        "JOBOPS_REQUIRE_OS_SANDBOX",
        "JOBOPS_AGENT_WORKSPACE",
        "NO_COLOR",
        "CI",
    }
)

# Informational role hints written by the orchestrator into agent env.
AGENT_HINT_KEYS = frozenset(
    {
        "JOBOPS_AGENT_ROLE",
        "JOBOPS_ALLOWED_TOOLS",
        "JOBOPS_BROKER_SESSION",
        "JOBOPS_POLICY_VERSION",
        "JOBOPS_SANDBOX_MODE",
    }
)


def is_secret_env_key(key: str) -> bool:
    if key in SECRET_ENV_EXACT:
        return True
    return any(key.startswith(p) for p in SECRET_ENV_PREFIXES)


@dataclass
class OrchestratorAuthority:
    """
    Sealed capability proving the current process stack is the trusted orchestrator.
    Agents never receive this token (not via env inheritance).
    """

    token: str
    principal: str = "orchestrator"
    scopes: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"approve", "issue_evidence", "reserve_submit", "record_approval"}
        )
    )
    grant_id: str = ""
    workspace_home: str = ""

    def permits(self, scope: str) -> bool:
        return scope in self.scopes


_tls = threading.local()


def _stack() -> list[OrchestratorAuthority]:
    stack = getattr(_tls, "orchestrator_stack", None)
    if stack is None:
        stack = []
        _tls.orchestrator_stack = stack
    return stack


def current_orchestrator() -> Optional[OrchestratorAuthority]:
    stack = _stack()
    return stack[-1] if stack else None


def require_orchestrator(scope: str) -> OrchestratorAuthority:
    """Fail closed unless a live OrchestratorContext permits ``scope``."""
    auth = current_orchestrator()
    if auth is None:
        raise PermissionError(f"orchestrator_context_required:{scope}")
    if not auth.permits(scope):
        raise PermissionError(f"orchestrator_scope_denied:{scope}")
    return auth


def agent_role_from_env(environ: Optional[Mapping[str, str]] = None) -> str:
    env = environ if environ is not None else os.environ
    return (env.get("JOBOPS_AGENT_ROLE") or "").strip()


def is_untrusted_agent_role(role: str) -> bool:
    return role in {
        "discovery",
        "verification",
        "frontier_rank",
        "frontier_submit",
        "outreach",
    }


@contextmanager
def OrchestratorContext(
    *,
    grant: "AuthorityGrant",
    workspace_home: Path | str,
    principal: Optional[str] = None,
) -> Iterator[OrchestratorAuthority]:
    """
    Enter the trusted control plane using a verified AuthorityGrant.

    Application code cannot self-mint privileges: a ControlPlaneController-issued
    grant is required. Untrusted agent roles cannot open this context even after
    clearing JOBOPS_AGENT_ROLE in a contaminated process (grant verification
    still requires the workspace authority key + non-agent role).
    """
    from authority import note_agent_role, verify_authority_grant

    role = agent_role_from_env()
    note_agent_role(role)
    if is_untrusted_agent_role(role):
        raise PermissionError(f"orchestrator_context_forbidden_in_agent_role:{role}")
    home = Path(workspace_home).expanduser().resolve()
    verified = verify_authority_grant(grant, workspace_home=home)
    if principal is not None and verified.principal != principal:
        raise PermissionError("orchestrator_principal_mismatch")
    auth = OrchestratorAuthority(
        token=verified.signature,
        principal=verified.principal,
        scopes=verified.scopes,
        grant_id=verified.grant_id,
        workspace_home=str(home),
    )
    _stack().append(auth)
    try:
        yield auth
    finally:
        stack = _stack()
        if stack and stack[-1] is auth:
            stack.pop()
        elif auth in stack:
            stack.remove(auth)


@contextmanager
def open_orchestrator(
    workspace_home: Path | str,
    *,
    principal: str = "orchestrator",
    scopes: Optional[Sequence[str]] = None,
) -> Iterator[OrchestratorAuthority]:
    """Bootstrap control plane (if needed), issue a grant, and enter context."""
    from authority import issue_test_grant

    home = Path(workspace_home).expanduser().resolve()
    grant = issue_test_grant(home, principal=principal, scopes=scopes)
    with OrchestratorContext(grant=grant, workspace_home=home) as auth:
        yield auth


def build_agent_subprocess_env(
    *,
    role: str,
    allowed_tools: Sequence[str] = (),
    broker_session_id: str = "",
    policy_version: str = "",
    parent_env: Optional[Mapping[str, str]] = None,
    extra: Optional[Mapping[str, str]] = None,
    sandbox_mode: str = "broker",
) -> dict[str, str]:
    """
    Build an explicit minimal environment for untrusted agent subprocesses.

    Does **not** inherit the full parent environment. Secrets, approval
    credentials, JOBOPS_HOME, and PYTHONPATH are stripped even if present in
    ``extra``.
    """
    from authority import note_agent_role

    note_agent_role(role)
    parent = parent_env if parent_env is not None else os.environ
    out: dict[str, str] = {}
    for key in _AGENT_ENV_BASE_ALLOW:
        if key in parent and not is_secret_env_key(key):
            out[key] = str(parent[key])
    for key, val in parent.items():
        if key.startswith("LC_") and key not in out and not is_secret_env_key(key):
            out[key] = str(val)
    if extra:
        for key, val in extra.items():
            if is_secret_env_key(key):
                continue
            if key in {
                "JOBOPS_ALLOWED_TOOLS",
                "JOBOPS_AGENT_ROLE",
                "JOBOPS_CAPABILITY_TOKEN",
                "JOBOPS_HOME",
                "PYTHONPATH",
            }:
                continue
            if key in _AGENT_ENV_BASE_ALLOW or key.startswith("LC_"):
                out[key] = str(val)
    out["JOBOPS_AGENT_ROLE"] = role
    out["JOBOPS_ALLOWED_TOOLS"] = ",".join(sorted(str(t) for t in allowed_tools))
    if broker_session_id:
        out["JOBOPS_BROKER_SESSION"] = broker_session_id
    if policy_version:
        out["JOBOPS_POLICY_VERSION"] = policy_version
    out["JOBOPS_SANDBOX_MODE"] = sandbox_mode
    # Hard deny paths / flags that would expose the control plane or signing material.
    for denied in (
        "JOBOPS_HOME",
        "PYTHONPATH",
        "JOBOPS_USER_WORKSPACE",
        "JOBOPS_CONTROL_PLANE",
        "JOBOPS_CONTROL_PLANE_TOKEN",
    ):
        out.pop(denied, None)
    for key in list(out):
        if is_secret_env_key(key):
            out.pop(key, None)
    return out


def assert_env_has_no_secrets(environ: Mapping[str, str]) -> None:
    leaked = sorted(k for k in environ if is_secret_env_key(k))
    if leaked:
        raise PermissionError(f"secret_env_leak:{','.join(leaked)}")


def assert_agent_env_isolated(environ: Mapping[str, str]) -> None:
    """Agent env must omit secrets and control-plane path hints."""
    assert_env_has_no_secrets(environ)
    for denied in ("JOBOPS_HOME", "PYTHONPATH", "JOBOPS_USER_WORKSPACE"):
        if denied in environ:
            raise PermissionError(f"agent_env_forbidden_key:{denied}")


def redact_env_for_log(environ: Mapping[str, str]) -> dict[str, str]:
    """Safe copy for logs — secret keys replaced with <redacted>."""
    out: dict[str, str] = {}
    for k, v in environ.items():
        out[k] = "<redacted>" if is_secret_env_key(k) else v
    return out


def mutate_environ_strip_secrets(environ: MutableMapping[str, str]) -> None:
    for key in list(environ):
        if is_secret_env_key(key):
            environ.pop(key, None)
