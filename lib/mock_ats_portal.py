#!/usr/bin/env python3
"""
In-process mock ATS browser journey (no live network).

Covers form entry → confirmation → timeout → duplicate-submit prevention.
Does not enable live automatic submission.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


class MockAtsError(RuntimeError):
    """Portal journey refused or failed."""


@dataclass
class MockAtsPortal:
    """
    Deterministic ATS simulator for E2E tests.

    States: idle → form_open → filled → submitting → confirmed | timed_out | blocked
    """

    portal_id: str = field(default_factory=lambda: f"portal-{uuid.uuid4().hex[:8]}")
    job_url: str = "https://jobs.example.test/mock/role"
    confirm_timeout_sec: float = 0.05
    _state: str = "idle"
    _fields: dict[str, str] = field(default_factory=dict)
    _confirmation_id: Optional[str] = None
    _submitted_once: bool = False
    _submit_started_at: Optional[float] = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def _log(self, kind: str, **detail: Any) -> None:
        self.events.append({"kind": kind, "state": self._state, **detail})

    @property
    def state(self) -> str:
        return self._state

    def open_form(self) -> dict[str, Any]:
        if self._state not in {"idle", "confirmed", "timed_out", "blocked"}:
            raise MockAtsError(f"cannot_open_form_from:{self._state}")
        if self._submitted_once and self._state == "confirmed":
            self._state = "blocked"
            self._log("duplicate_open_blocked")
            raise MockAtsError("duplicate_submit_prevented")
        self._state = "form_open"
        self._fields = {}
        self._confirmation_id = None
        self._submit_started_at = None
        self._log("form_opened")
        return {"ok": True, "state": self._state, "fields": ["name", "email", "resume"]}

    def fill_field(self, name: str, value: str) -> dict[str, Any]:
        if self._state not in {"form_open", "filled"}:
            raise MockAtsError(f"cannot_fill_from:{self._state}")
        if name not in {"name", "email", "resume"}:
            raise MockAtsError(f"unknown_field:{name}")
        self._fields[name] = value
        required = {"name", "email", "resume"}
        self._state = "filled" if required <= set(self._fields) else "form_open"
        self._log("field_filled", field=name)
        return {"ok": True, "state": self._state, "filled": sorted(self._fields)}

    def submit(self, *, force_timeout: bool = False) -> dict[str, Any]:
        if self._state != "filled":
            raise MockAtsError(f"cannot_submit_from:{self._state}")
        if self._submitted_once:
            self._state = "blocked"
            self._log("duplicate_submit_blocked")
            raise MockAtsError("duplicate_submit_prevented")
        self._state = "submitting"
        self._submit_started_at = time.monotonic()
        self._log("submit_clicked")
        if force_timeout:
            # Leave in submitting; caller must poll confirmation.
            return {"ok": False, "state": self._state, "pending": True}
        return self.await_confirmation(timeout_sec=self.confirm_timeout_sec)

    def await_confirmation(self, *, timeout_sec: Optional[float] = None) -> dict[str, Any]:
        if self._state == "confirmed":
            return {
                "ok": True,
                "state": self._state,
                "confirmation_id": self._confirmation_id,
            }
        if self._state == "blocked":
            raise MockAtsError("duplicate_submit_prevented")
        if self._state != "submitting":
            raise MockAtsError(f"cannot_await_from:{self._state}")
        limit = self.confirm_timeout_sec if timeout_sec is None else timeout_sec
        started = self._submit_started_at or time.monotonic()
        # Simulate network wait; if caller passes tiny timeout, mark uncertain.
        elapsed = time.monotonic() - started
        if elapsed > limit or limit <= 0:
            self._state = "timed_out"
            self._log("confirmation_timeout")
            return {
                "ok": False,
                "state": self._state,
                "outcome": "SubmissionUncertain",
                "retryable": False,
            }
        # Immediate success path for tests that await promptly.
        self._confirmation_id = f"conf-{uuid.uuid4().hex[:12]}"
        self._state = "confirmed"
        self._submitted_once = True
        self._log("confirmed", confirmation_id=self._confirmation_id)
        return {
            "ok": True,
            "state": self._state,
            "confirmation_id": self._confirmation_id,
            "outcome": "Applied",
        }

    def try_submit_again(self) -> dict[str, Any]:
        """Explicit duplicate attempt after a prior confirmation."""
        if not self._submitted_once:
            raise MockAtsError("no_prior_submit")
        self._state = "blocked"
        self._log("duplicate_submit_blocked")
        raise MockAtsError("duplicate_submit_prevented")
