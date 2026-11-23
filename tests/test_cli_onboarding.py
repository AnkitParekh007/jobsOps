"""P1.8 — portable CLI init/doctor smoke."""
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
