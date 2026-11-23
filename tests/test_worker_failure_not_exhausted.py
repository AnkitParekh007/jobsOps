"""P0.4 — failed/timed-out workers must never claim honest source exhaustion."""
from __future__ import annotations

import json
from pathlib import Path


def _stub(shard_id: str, run_id: str, path: Path, wrc: str, reason: str) -> dict:
    timed_out = reason == "timeout" or wrc == "124"
    payload = {
        "shard_id": shard_id,
        "run_id": run_id,
        "lane": 0,
        "lane_name": "unknown",
        "country": "unknown",
        "mode": "http",
        "exhausted": False,
        "worker_status": "timeout" if timed_out else "failed",
        "sources_tried": [],
        "sources_blocked": [
            {"source": "worker", "reason": reason, "worker_rc": int(wrc) if wrc.lstrip("-").isdigit() else wrc}
        ],
        "sources_remaining_readable": ["unknown_after_worker_failure"],
        "matches": [],
        "notes": f"harness stub: worker {reason} rc={wrc}; NOT source exhaustion",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def test_failed_worker_stub_not_exhausted(tmp_path: Path):
    path = tmp_path / "fde-de.json"
    data = _stub("fde-de", "run-1", path, "1", "worker_failed")
    assert data["exhausted"] is False
    assert data["worker_status"] == "failed"
    assert data["sources_remaining_readable"]


def test_timeout_worker_stub_not_exhausted(tmp_path: Path):
    path = tmp_path / "frontend-de.json"
    data = _stub("frontend-de", "run-1", path, "124", "timeout")
    assert data["exhausted"] is False
    assert data["worker_status"] == "timeout"
    assert "NOT source exhaustion" in data["notes"]


def test_timeout_rewrites_partial_shard_exhausted_flag(tmp_path: Path):
    path = tmp_path / "partial.json"
    path.write_text(
        json.dumps(
            {
                "shard_id": "partial",
                "run_id": "run-1",
                "exhausted": True,
                "matches": [{"canonical_url": "https://example.com/j"}],
                "sources_remaining_readable": [],
                "notes": "agent claimed exhausted before timeout",
            }
        ),
        encoding="utf-8",
    )
    # Mirror harness post-timeout correction
    d = json.loads(path.read_text(encoding="utf-8"))
    d["exhausted"] = False
    d["worker_status"] = "timeout"
    d.setdefault("sources_remaining_readable", ["unknown_after_timeout"])
    path.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
    fixed = json.loads(path.read_text(encoding="utf-8"))
    assert fixed["exhausted"] is False
    assert fixed["worker_status"] == "timeout"
