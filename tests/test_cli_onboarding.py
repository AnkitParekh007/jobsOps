"""P1.8 — portable CLI init/doctor smoke + preview mode."""
from __future__ import annotations

import json
from pathlib import Path

from jobops.cli import main


def test_init_and_doctor(tmp_path: Path, capsys):
    home = tmp_path / "ws"
    rc = main(["init", "--workspace", str(home), "--name", "Alex Candidate", "--countries", "Remote"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert (home / "candidate-profile.json").is_file()

    rc = main(["doctor", "--workspace", str(home)])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is True
    assert doc["checks"]["submit_default_off"] is True


def test_preview_is_non_mutating(tmp_path: Path, capsys):
    rc = main(["run", "--workflow", "discovery", "--preview", "--runtime", "deterministic"])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["ok"] is True
    assert plan["preview"] is True
    assert plan["mutating"] is False
    assert plan["invoked_harness"] is False
    assert "no harness" in plan["preview_semantics"]
