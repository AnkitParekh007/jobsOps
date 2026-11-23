#!/usr/bin/env python3
"""
Capability broker — runtime enforcement of agent tool permissions.

Allowlists in prompts or JOBOPS_ALLOWED_TOOLS env are informational only.
All jobsOps-mediated tool dispatch must go through ToolBroker.invoke().
Agents cannot widen scopes after a session is sealed.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

ToolHandler = Callable[..., Any]


def _runtime():
    """Lazy import to avoid circular dependency with agent_runtime."""
    import agent_runtime as ar  # noqa: WPS433

    return ar


@dataclass(frozen=True)
class CapabilityToken:
    """Opaque capability; possession alone is insufficient without broker.verify()."""

    token_id: str
    role: str
    tools: frozenset[str]
    session_id: str


@dataclass
class ToolBroker:
    """
    Sealed capability session for one agent role.

    - Scopes are frozen at construction; env/prompt cannot expand them.
    - Privileged tools (browser/submit) require an explicit grant at create time
      and are refused for non-submit roles regardless of requested lists.
    - invoke() is the only sanctioned dispatch path for jobsOps tool handlers.
    """

    role: str
    session_id: str
    allowed_tools: frozenset[str]
    token: CapabilityToken
    _handlers: dict[str, ToolHandler] = field(default_factory=dict, repr=False)
    _closed: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    # Audit of denied attempts (for adversarial tests / observability).
    denials: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        role: str,
        *,
        requested: Optional[Sequence[str]] = None,
        session_id: Optional[str] = None,
        handlers: Optional[Mapping[str, ToolHandler]] = None,
    ) -> "ToolBroker":
        ar = _runtime()
        allowed = ar.resolve_allowed_tools(role, requested)
        sid = session_id or secrets.token_hex(8)
        token = CapabilityToken(
            token_id=secrets.token_hex(16),
            role=role,
            tools=frozenset(allowed),
            session_id=sid,
        )
        broker = cls(
            role=role,
            session_id=sid,
            allowed_tools=frozenset(allowed),
            token=token,
        )
        if handlers:
            for name, fn in handlers.items():
                broker.register(name, fn)
        return broker

    def register(self, tool: str, handler: ToolHandler) -> None:
        ar = _runtime()
        with self._lock:
            if self._closed:
                raise ar.ToolPermissionError("broker_closed")
            if tool not in self.allowed_tools:
                raise ar.ToolPermissionError(
                    f"cannot register tool={tool} outside sealed allowlist "
                    f"for role={self.role}"
                )
            self._handlers[tool] = handler

    def verify_token(self, token_id: str) -> bool:
        return (not self._closed) and secrets.compare_digest(self.token.token_id, token_id)

    def permits(self, tool: str) -> bool:
        ar = _runtime()
        if self._closed:
            return False
        if tool not in self.allowed_tools:
            return False
        if tool in ar.PRIVILEGED_TOOLS and self.role != "frontier_submit":
            return False
        return True

    def invoke(
        self,
        tool: str,
        *args: Any,
        token_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """
        Dispatch a registered tool handler after capability checks.
        Refuses unknown tools, closed brokers, forged tokens, and scope bypass.
        """
        ar = _runtime()
        with self._lock:
            if self._closed:
                self.denials.append(f"closed:{tool}")
                raise ar.ToolPermissionError("broker_closed")
            if token_id is not None and not self.verify_token(token_id):
                self.denials.append(f"bad_token:{tool}")
                raise ar.ToolPermissionError("invalid_capability_token")
            if not self.permits(tool):
                self.denials.append(f"denied:{tool}")
                raise ar.ToolPermissionError(
                    f"role={self.role} denied tool={tool} "
                    f"(sealed={','.join(sorted(self.allowed_tools))})"
                )
            handler = self._handlers.get(tool)
            if handler is None:
                self.denials.append(f"unregistered:{tool}")
                raise ar.ToolPermissionError(f"tool_not_registered:{tool}")
            return handler(*args, **kwargs)

    def attempt_widen(self, extra_tools: Sequence[str]) -> None:
        """
        Explicitly refuse post-seal widen attempts (env/prompt injection simulation).
        Always raises — scopes are immutable after create().
        """
        ar = _runtime()
        extras = frozenset(str(t) for t in extra_tools) - self.allowed_tools
        if extras:
            self.denials.append(f"widen:{','.join(sorted(extras))}")
            raise ar.ToolPermissionError(
                f"scope_widen_refused: {', '.join(sorted(extras))}"
            )
        # No-op widen of already-allowed tools still refused as API misuse.
        raise ar.ToolPermissionError("scope_immutable_after_seal")

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._handlers.clear()

    def to_public_dict(self) -> dict[str, Any]:
        """Safe summary for logs — never includes the raw capability token."""
        return {
            "role": self.role,
            "session_id": self.session_id,
            "allowed_tools": sorted(self.allowed_tools),
            "closed": self._closed,
            "token_present": bool(self.token.token_id),
            # Hint only — child processes must not treat this as authorization.
            "env_hint_informational_only": True,
        }


def broker_from_role(
    role: str,
    *,
    requested: Optional[Sequence[str]] = None,
    session_id: Optional[str] = None,
) -> ToolBroker:
    """Factory used by AgentRuntime at invoke boundary."""
    return ToolBroker.create(role, requested=requested, session_id=session_id)
