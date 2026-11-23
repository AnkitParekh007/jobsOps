"""Phase 0: merge must preserve reason / evidence from discovery shards."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "lib"
FIXTURE_SHARDS = ROOT / "tests" / "fixtures" / "20261123-1900IST" / "shards"
MERGE_SCRIPT = LIB / "merge_shards.py"

sys.path.insert(0, str(LIB))
from merge_shards import normalize_match  # noqa: E402


def test_normalize_match_preserves_reason_and_evidence() -> None:
    raw = {
        "canonical_url": "https://jobs.example.com/roles/123?utm=x",
        "organization": "Example",
        "role": "FDE",
        "status": "Needs review",
        "lane": "fde",
        "country": "DE",
        "source": "greenhouse",
        "employer_or_ats_url": "https://boards.greenhouse.io/example/jobs/123",
        "reason": "Sponsorship not evidenced on posting",
        "evidence_quote": "Must be eligible to work in Germany",
    }
    out = normalize_match(raw, "fixture-shard")
    assert out is not None
    assert out["reason"] == "Sponsorship not evidenced on posting"
    assert out["employer_or_ats_url"] == "https://boards.greenhouse.io/example/jobs/123"
    assert out["evidence_quote"] == "Must be eligible to work in Germany"
    assert out["canonical_url"] == "https://jobs.example.com/roles/123"
    assert out["shard_id"] == "fixture-shard"


def test_normalize_match_omits_empty_evidence_quote() -> None:
    raw = {
        "canonical_url": "https://jobs.example.com/roles/456",
        "status": "Skipped",
        "reason": "Hard language gate",
        "employer_or_ats_url": "https://jobs.example.com/roles/456",
    }
    out = normalize_match(raw, "s1")
    assert out is not None
    assert out["reason"] == "Hard language gate"
    assert "evidence_quote" not in out


def test_offline_remerge_1900ist_preserves_all_reasons(tmp_path: Path) -> None:
    assert FIXTURE_SHARDS.is_dir(), f"missing fixtures: {FIXTURE_SHARDS}"
    shard_files = list(FIXTURE_SHARDS.glob("*.json"))
    assert shard_files, "expected cloned 1900IST shard JSON fixtures"

    out_path = tmp_path / "handoff-state.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(MERGE_SCRIPT),
            "--shards-dir",
            str(FIXTURE_SHARDS),
            "--out",
            str(out_path),
            "--run-id",
            "20261123-1900IST-remerge-test",
            "--floor",
            "40",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout

    state = json.loads(out_path.read_text(encoding="utf-8"))
    matches = state.get("matches") or []
    assert matches, "expected merged matches from 1900IST fixtures"

    with_reason = sum(
        1 for m in matches if isinstance(m.get("reason"), str) and m["reason"].strip()
    )
    assert with_reason == len(matches), (
        f"reasons dropped: with_reason={with_reason} len(matches)={len(matches)}"
    )

    # Every merged match should keep employer_or_ats_url.
    missing_employer = [
        m.get("canonical_url")
        for m in matches
        if not (isinstance(m.get("employer_or_ats_url"), str) and m["employer_or_ats_url"].startswith("http"))
    ]
    assert not missing_employer

    # Spot-check: at least one fixture reason survives verbatim.
    reasons = {m["reason"] for m in matches}
    assert any("Sponsorship not evidenced" in r for r in reasons)
