"""E07 Materials / PDF gates — ATS/quality floors, fingerprint, no invented skills."""
from __future__ import annotations

import json
from pathlib import Path

from submission_authorize import (
    STATE_PREPARING,
    STATE_READY_FOR_APPROVAL,
    authorize_submission,
    fingerprint_text,
    validate_materials,
)

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures" / "e07"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


MARKERS = ["alex", "candidate"]


def test_materials_pass_dry_run_ready_for_approval():
    data = _load("materials_pass.json")
    result = authorize_submission(
        data,
        run_id="e07-pass",
        dry_run=True,
        require_form_lock=False,
        submits_today=0,
        identity_markers=MARKERS,
    )
    assert result.state == STATE_READY_FOR_APPROVAL
    assert result.authorized is False
    assert result.sop_status == "Ready for approval"
    assert result.package["ats_score"] >= 80
    assert result.package["quality_score"] >= 75
    assert result.package["evidence_package"].get("ready_for_approval") is True


def test_dry_run_full_evidence_package():
    data = _load("dry_run_ready_package.json")
    result = authorize_submission(
        data,
        run_id="e07-dryrun",
        dry_run=True,
        require_form_lock=False,
        submits_today=0,
        identity_markers=MARKERS,
    )
    assert result.state == data["expected_state"]
    assert result.sop_status == data["expected_sop_status"]
    pkg = result.package
    assert pkg["pdf_fingerprint"]
    assert pkg["evidence_package"]["dry_run"] is True
    assert "Alex" in pkg["extracted_text"]
    # Schema-valid package
    from contracts import validate

    validate(pkg, "application-package.schema.json")


def test_ats_below_floor():
    data = _load("ats_below_floor.json")
    result = authorize_submission(
        data,
        run_id="e07-ats",
        dry_run=True,
        require_form_lock=False,
        submits_today=0,
        identity_markers=MARKERS,
    )
    assert result.state == STATE_PREPARING
    assert any(data["expected_blocking_substring"] in b for b in result.blocking_reasons)


def test_invented_python_claim():
    data = _load("invented_python_claim.json")
    ok, blocking = validate_materials(
        extracted_text=data["extracted_text"],
        ats_score=data["ats_score"],
        quality_score=data["quality_score"],
        pdf_fingerprint=data["pdf_fingerprint"],
        ats_score_fingerprint=data["ats_score_fingerprint"],
        quality_score_fingerprint=data["quality_score_fingerprint"],
        fingerprint_method=data["fingerprint_method"],
        identity_markers=MARKERS,
        allow_fixture_method=True,
    )
    assert not ok
    assert any("invented_claim" in b for b in blocking)


def test_fingerprint_mismatch():
    data = _load("fingerprint_mismatch.json")
    result = authorize_submission(
        data,
        run_id="e07-fp",
        dry_run=True,
        require_form_lock=False,
        submits_today=0,
        identity_markers=MARKERS,
    )
    assert result.state == STATE_PREPARING
    assert any(data["expected_blocking_substring"] in b for b in result.blocking_reasons)


def test_fingerprint_text_stable():
    a = fingerprint_text("Alex  Candidate\nReact")
    b = fingerprint_text("Alex Candidate React")
    assert a == b
    assert len(a) == 64
