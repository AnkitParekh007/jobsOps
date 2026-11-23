"""E10 Learning safety — proposals cannot mutate policy without approval fixture."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from contracts import validate
from learning_proposals import (
    POLICY_PATH,
    LearningSafetyError,
    apply_policy_mutation_forbidden,
    generate_weekly_batch,
    outcome_analyst,
    policy_proposal,
)
from ledger import Ledger

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e10"


def _policy_digest() -> str:
    return hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()


def test_learning_events_are_proposal_only():
    jobs = json.loads((FIX / "learning_batch_jobs.json").read_text(encoding="utf-8"))["jobs"]
    l01 = outcome_analyst(jobs, lane_country="1|Germany")
    assert l01["proposal_only"] is True
    assert l01["mutates_policy"] is False
    assert l01["approval_required"] is True
    validate(l01, "learning-event.schema.json")


def test_policy_proposal_never_writes_policy_file():
    before = _policy_digest()
    jobs = json.loads((FIX / "learning_batch_jobs.json").read_text(encoding="utf-8"))["jobs"]
    prop = policy_proposal(lane_country="Germany", matured_apps=2)
    assert prop["mutates_policy"] is False
    validate(prop, "learning-event.schema.json")
    after = _policy_digest()
    assert before == after


def test_apply_policy_mutation_blocked_without_approval():
    prop = policy_proposal(matured_apps=0)
    with pytest.raises(LearningSafetyError):
        apply_policy_mutation_forbidden(prop, approved=False)


def test_apply_policy_mutation_blocked_even_when_approved():
    """Approved still requires manual edit — auto-write forbidden."""
    prop = policy_proposal(matured_apps=25)
    with pytest.raises(LearningSafetyError, match="manual"):
        apply_policy_mutation_forbidden(prop, approved=True)
    assert _policy_digest() == hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()


def test_weekly_batch_writes_artifacts_not_policy(tmp_path: Path):
    before = _policy_digest()
    jobs = json.loads((FIX / "learning_batch_jobs.json").read_text(encoding="utf-8"))["jobs"]
    db = tmp_path / "jobops.db"
    led = Ledger(db)
    led.start_run("e10-batch", floor=0, phase="learning")
    batch = generate_weekly_batch(jobs, run_id="e10-batch", ledger=led)
    assert batch["mutates_policy"] is False
    assert batch["policy_path_untouched"] is True
    assert batch["l03"]["approval_status"] == "pending"
    validate(batch["l03"], "experiment-proposal.schema.json")
    arts = led._conn.execute(
        "SELECT COUNT(*) AS c FROM artifacts WHERE artifact_type IN ('learning_event','experiment_proposal')"
    ).fetchone()
    assert arts["c"] >= 4
    led.close()
    assert before == _policy_digest()
