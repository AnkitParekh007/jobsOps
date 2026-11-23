"""Policy unit tests: tools, caps, transitions, denylist."""
from __future__ import annotations

from policy import (
    DAILY_SUBMIT_CAP,
    HANDOFF_FLOOR_DEFAULT,
    can_transition,
    check_daily_submit_cap,
    check_handoff_floor,
    check_verified_fact_claim,
    tool_allowed,
)


def test_daily_submit_cap_is_one():
    assert DAILY_SUBMIT_CAP == 1
    assert check_daily_submit_cap(0).ok
    assert not check_daily_submit_cap(1).ok


def test_handoff_floor_default_40():
    assert HANDOFF_FLOOR_DEFAULT == 40
    assert check_handoff_floor(40).ok
    assert not check_handoff_floor(39).ok


def test_discovery_cannot_browser_or_submit():
    assert not tool_allowed("discovery", "browser").ok
    assert not tool_allowed("discovery", "submit").ok
    assert tool_allowed("discovery", "http_fetch").ok


def test_frontier_submit_may_browser_with_note():
    v = tool_allowed("frontier_submit", "browser")
    assert v.ok


def test_status_transitions_sop15():
    assert can_transition("New", "Eligible").ok
    assert can_transition("Eligible", "In preparation").ok
    assert can_transition("Submitted", "Applied").ok
    assert not can_transition("Skipped", "Eligible").ok
    assert not can_transition("Applied", "Eligible").ok


def test_verified_fact_denylist():
    assert not check_verified_fact_claim("Candidate has expert in python").ok
    assert check_verified_fact_claim("Enterprise Angular and React").ok
