"""
P0-01 / P0-02 negative tests: control-plane bootstrap + confirmation channels.

Untrusted contexts must not become trusted merely by setting
JOBOPS_CONTROL_PLANE=1, clearing role flags, or calling the installer.
Production authorization must refuse synthetic confirmation channels.
"""
from __future__ import annotations

import importlib
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

from approval_controller import (
    ApprovalAuthError,
    ApprovalController,
    issue_confirmed_session,
    resolve_confirmation_channel,
)
from authority import (
    AuthorityError,
    ControlPlaneController,
    bootstrap_control_plane,
    install_control_plane_privilege,
    issue_orchestrator_grant,
    privilege_path,
    reset_control_plane_for_tests,
)
from confirmation_test_channels import (
    EchoChallengeChannel,
    ForgedTrustedInteractiveEchoChannel,
    ProgrammaticEchoChannel,
)
from ledger import Ledger
from trust_boundary import open_orchestrator


def test_control_plane_flag_alone_cannot_bootstrap(tmp_path, monkeypatch):
    """P0-01: setting JOBOPS_CONTROL_PLANE=1 without privilege fails closed."""
    home = tmp_path / "flag-only"
    home.mkdir()
    (home / "secrets").mkdir()
    (home / "state").mkdir()
    monkeypatch.setenv("JOBOPS_CONTROL_PLANE", "1")
    monkeypatch.setenv("JOBOPS_HOME", str(home))
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    reset_control_plane_for_tests()
    with pytest.raises(AuthorityError, match="privilege"):
        bootstrap_control_plane(home)
    with pytest.raises(AuthorityError, match="privilege"):
        issue_orchestrator_grant(home, principal="attacker")
    with pytest.raises(AuthorityError, match="privilege"):
        with open_orchestrator(home, principal="attacker"):
            pass


def test_clearing_role_flags_cannot_elevate(jobops_home: Path, monkeypatch):
    """P0-01: clearing JOBOPS_AGENT_ROLE after contamination cannot elevate."""
    reset_control_plane_for_tests()
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "discovery")
    with pytest.raises(AuthorityError, match="agent"):
        bootstrap_control_plane(jobops_home)
    # Adversary clears role flags — contamination must persist.
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    monkeypatch.setenv("JOBOPS_CONTROL_PLANE", "1")
    with pytest.raises(AuthorityError, match="contamination"):
        bootstrap_control_plane(jobops_home)
    with pytest.raises(AuthorityError, match="contamination|agent"):
        install_control_plane_privilege(jobops_home)
    with pytest.raises(AuthorityError, match="contamination|agent"):
        ControlPlaneController(jobops_home)


def test_installer_from_untrusted_context_cannot_create_trust(tmp_path, monkeypatch):
    """P0-01: calling the installer under an agent role cannot mint trust."""
    home = tmp_path / "installer-untrusted"
    home.mkdir()
    (home / "secrets").mkdir()
    (home / "state").mkdir()
    monkeypatch.setenv("JOBOPS_HOME", str(home))
    monkeypatch.setenv("JOBOPS_CONTROL_PLANE", "1")
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "frontier_submit")
    reset_control_plane_for_tests()
    with pytest.raises(AuthorityError, match="agent"):
        install_control_plane_privilege(home)
    assert not privilege_path(home).is_file()
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    # Contamination from the agent role attempt blocks subsequent provision.
    with pytest.raises(AuthorityError, match="contamination"):
        install_control_plane_privilege(home)


def test_reset_control_plane_forbidden_outside_authenticated_tests(monkeypatch):
    """P1: production code cannot clear contamination via the test reset helper."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("JOBOPS_ALLOW_TEST_CONTROL_PLANE_RESET", "0")
    with pytest.raises(AuthorityError, match="reset_forbidden_outside_tests"):
        reset_control_plane_for_tests()


def test_reset_flag_alone_without_pytest_forbidden(monkeypatch):
    """P1: JOBOPS_ALLOW_TEST_CONTROL_PLANE_RESET alone never unlocks production."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("JOBOPS_ALLOW_TEST_CONTROL_PLANE_RESET", "1")
    with pytest.raises(AuthorityError, match="reset_forbidden_outside_tests"):
        reset_control_plane_for_tests()


def test_init_cli_source_does_not_install_privilege():
    """P0-01 static guard: cmd_init must never provision authority credentials."""
    import jobops.cli as cli

    src = inspect.getsource(cli.cmd_init)
    assert "install_control_plane_privilege" not in src
    assert "bootstrap_control_plane" not in src
    assert "issue_test_grant" not in src
    assert "control_plane.privilege" not in src


def test_approve_cli_source_does_not_reset_or_install_or_clear_role():
    """P0-01 static guard: cmd_approve must not privilege-elevate via test helpers."""
    import jobops.cli as cli

    src = inspect.getsource(cli.cmd_approve)
    assert "reset_control_plane_for_tests" not in src
    assert "install_control_plane_privilege" not in src
    assert "os.environ.pop(\"JOBOPS_AGENT_ROLE\"" not in src
    assert "os.environ.pop('JOBOPS_AGENT_ROLE'" not in src
    assert "setdefault(\"JOBOPS_CONTROL_PLANE\"" not in src
    # Provisioning is a separate command.
    assert hasattr(cli, "cmd_control_plane_provision")
    prov_src = inspect.getsource(cli.cmd_control_plane_provision)
    assert "install_control_plane_privilege" in prov_src


def test_approve_cli_requires_preexisting_privilege(tmp_path, monkeypatch):
    """P0-01: jobops approve fails when privilege was never provisioned."""
    home = tmp_path / "approve-no-priv"
    home.mkdir()
    (home / "secrets").mkdir()
    (home / "state").mkdir()
    monkeypatch.setenv("JOBOPS_HOME", str(home))
    monkeypatch.setenv("JOBOPS_CONTROL_PLANE", "1")
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    reset_control_plane_for_tests()
    from jobops.cli import main

    rc = main(
        [
            "approve",
            "--approval-id",
            "a1",
            "--principal",
            "owner",
            "--job-key",
            "job:1",
            "--session-id",
            "sess-1",
            "--fingerprint",
            "a" * 64,
            "--workspace",
            str(home),
        ]
    )
    assert rc == 2


def test_approve_cli_does_not_clear_agent_role(tmp_path, monkeypatch):
    """P0-01: approve refuses agent roles instead of clearing them."""
    home = tmp_path / "approve-role"
    home.mkdir()
    (home / "secrets").mkdir()
    (home / "state").mkdir()
    monkeypatch.setenv("JOBOPS_HOME", str(home))
    monkeypatch.setenv("JOBOPS_CONTROL_PLANE", "1")
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "discovery")
    reset_control_plane_for_tests()
    # Pre-install privilege as a different trusted process would have.
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    install_control_plane_privilege(home)
    monkeypatch.setenv("JOBOPS_AGENT_ROLE", "discovery")
    from jobops.cli import main

    rc = main(
        [
            "approve",
            "--approval-id",
            "a1",
            "--principal",
            "owner",
            "--job-key",
            "job:1",
            "--session-id",
            "sess-1",
            "--fingerprint",
            "a" * 64,
            "--workspace",
            str(home),
        ]
    )
    assert rc == 2
    assert os.environ.get("JOBOPS_AGENT_ROLE") == "discovery"


def test_programmatic_challenge_echo_rejected_without_test_auth(
    jobops_home: Path, monkeypatch
):
    """P0-02: programmatic challenge echo cannot substitute into production."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    monkeypatch.setenv("JOBOPS_ALLOW_TEST_CONFIRMATION", "0")
    led = Ledger(jobops_home / "state" / "echo.db")
    led.start_run("echo-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="echo",
            user_id="owner",
            job_key="job:echo",
            session_id="sess-echo",
            artifact_fingerprint="a" * 64,
        )
        with pytest.raises(
            ApprovalAuthError, match="confirmation_channel_substitution_forbidden"
        ):
            issue_confirmed_session(
                ledger=led,
                workspace_home=jobops_home,
                user_id="owner",
                approval_id="echo",
                channel=ProgrammaticEchoChannel(),
            )
        with pytest.raises(
            ApprovalAuthError, match="confirmation_channel_substitution_forbidden"
        ):
            resolve_confirmation_channel(
                EchoChallengeChannel(), workspace_home=jobops_home
            )
    led.close()


def test_confirmation_channel_substitution_rejected(jobops_home: Path, monkeypatch):
    """P0-02: injecting EchoChallengeChannel into interactive_approve needs test auth."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    monkeypatch.setenv("JOBOPS_ALLOW_TEST_CONFIRMATION", "0")
    led = Ledger(jobops_home / "state" / "sub.db")
    led.start_run("sub-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="sub",
            user_id="owner",
            job_key="job:sub",
            session_id="sess-sub",
            artifact_fingerprint="b" * 64,
        )
        with pytest.raises(
            ApprovalAuthError, match="confirmation_channel_substitution_forbidden"
        ):
            ctl.interactive_approve(
                approval_id="sub",
                principal="owner",
                expected_job_key="job:sub",
                expected_session_id="sess-sub",
                expected_fingerprint="b" * 64,
                channel=EchoChallengeChannel(),
                workspace_home=jobops_home,
            )
    led.close()


def test_echo_channel_not_exported_from_production_module():
    """P0-02: EchoChallengeChannel lives in test helpers, not production auth."""
    import approval_controller as ac

    assert not hasattr(ac, "EchoChallengeChannel")
    assert not hasattr(ac, "FabricatedConfirmationChannel")
    assert not hasattr(ac, "ForgedTrustedInteractiveEchoChannel")
    # Attribute markers are not a trust API.
    assert not hasattr(ac, "_TRUSTED_INTERACTIVE_ATTR")
    assert hasattr(ac, "_is_production_confirmation_channel")
    # Test helper module still provides them for authenticated fixtures.
    mod = importlib.import_module("confirmation_test_channels")
    assert hasattr(mod, "EchoChallengeChannel")
    assert hasattr(mod, "ForgedTrustedInteractiveEchoChannel")


def test_forged_trusted_interactive_attribute_cannot_approve(
    jobops_home: Path, monkeypatch
):
    """
    P0-03: a custom class that echoes the challenge and sets
    ``_jobops_trusted_interactive=True`` must not approve without test auth.
    """
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    monkeypatch.setenv("JOBOPS_ALLOW_TEST_CONFIRMATION", "0")
    led = Ledger(jobops_home / "state" / "forge-attr.db")
    led.start_run("forge-attr-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="forge-attr",
            user_id="owner",
            job_key="job:forge-attr",
            session_id="sess-forge-attr",
            artifact_fingerprint="d" * 64,
        )
        forged = ForgedTrustedInteractiveEchoChannel()
        assert getattr(forged, "_jobops_trusted_interactive", False) is True
        with pytest.raises(
            ApprovalAuthError, match="confirmation_channel_substitution_forbidden"
        ):
            resolve_confirmation_channel(forged, workspace_home=jobops_home)
        with pytest.raises(
            ApprovalAuthError, match="confirmation_channel_substitution_forbidden"
        ):
            ctl.interactive_approve(
                approval_id="forge-attr",
                principal="owner",
                expected_job_key="job:forge-attr",
                expected_session_id="sess-forge-attr",
                expected_fingerprint="d" * 64,
                channel=forged,
                workspace_home=jobops_home,
            )
        # Still pending — forged channel never decided it.
        row = led.get_approval("forge-attr")
        assert row is not None
        assert row["status"] == "pending"
    led.close()


def test_confirmation_flag_alone_without_pytest_forbidden(
    jobops_home: Path, monkeypatch
):
    """P1: JOBOPS_ALLOW_TEST_CONFIRMATION alone never unlocks production channels."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("JOBOPS_ALLOW_TEST_CONFIRMATION", "1")
    with pytest.raises(
        ApprovalAuthError, match="confirmation_channel_substitution_forbidden"
    ):
        resolve_confirmation_channel(
            EchoChallengeChannel(), workspace_home=jobops_home
        )
    with pytest.raises(
        ApprovalAuthError, match="confirmation_channel_substitution_forbidden"
    ):
        resolve_confirmation_channel(
            ForgedTrustedInteractiveEchoChannel(), workspace_home=jobops_home
        )


def test_replay_after_interactive_approve_rejected(jobops_home: Path, monkeypatch):
    """P0-02: replay of a consumed interactive approval fails."""
    monkeypatch.delenv("JOBOPS_AGENT_ROLE", raising=False)
    # Authenticated test confirmation allowed for the first (legitimate) approve.
    monkeypatch.setenv("JOBOPS_ALLOW_TEST_CONFIRMATION", "1")
    led = Ledger(jobops_home / "state" / "replay2.db")
    led.start_run("rp2-1", floor=40)
    with open_orchestrator(jobops_home, principal="pytest"):
        ctl = ApprovalController(led, workspace_home=jobops_home)
        ctl.request_approval(
            approval_id="rp2",
            user_id="owner",
            job_key="job:rp2",
            session_id="sess-rp2",
            artifact_fingerprint="c" * 64,
        )
        decided = ctl.interactive_approve(
            approval_id="rp2",
            principal="owner",
            expected_job_key="job:rp2",
            expected_session_id="sess-rp2",
            expected_fingerprint="c" * 64,
            channel=EchoChallengeChannel(),
            workspace_home=jobops_home,
        )
        assert decided["status"] == "approved"
        with pytest.raises(ApprovalAuthError, match="not_pending|consumed|mismatch"):
            ctl.interactive_approve(
                approval_id="rp2",
                principal="owner",
                expected_job_key="job:rp2",
                expected_session_id="sess-rp2",
                expected_fingerprint="c" * 64,
                channel=EchoChallengeChannel(),
                workspace_home=jobops_home,
            )
    led.close()


def test_child_cannot_elevate_via_flag_clear_role_and_installer(jobops_home: Path):
    """
    P0-01 cross-process: child that sets control-plane flag, clears role, and
    calls the installer still cannot become trusted after agent contamination.
    """
    reset_control_plane_for_tests()
    bootstrap_control_plane(jobops_home)
    from trust_boundary import build_agent_subprocess_env

    env = build_agent_subprocess_env(role="verification", parent_env=os.environ)
    assert "JOBOPS_CONTROL_PLANE" not in env
    assert "JOBOPS_ALLOW_TEST_CONFIRMATION" not in env
    assert "JOBOPS_ALLOW_TEST_CONTROL_PLANE_RESET" not in env
    lib = str(Path(__file__).resolve().parent.parent / "lib")
    script = f"""
import os, sys
sys.path.insert(0, {lib!r})
os.environ.pop('JOBOPS_AGENT_ROLE', None)
os.environ['JOBOPS_CONTROL_PLANE'] = '1'
os.environ['JOBOPS_HOME'] = {str(jobops_home)!r}
from authority import (
    ControlPlaneController,
    bootstrap_control_plane,
    install_control_plane_privilege,
    note_agent_role,
    reset_control_plane_for_tests,
)
note_agent_role('verification')
# Attempt the three elevation tricks from the finding.
try:
    reset_control_plane_for_tests()
    print('reset', 'UNEXPECTED_OK')
except Exception as exc:
    print('reset', type(exc).__name__, exc)
try:
    install_control_plane_privilege({str(jobops_home)!r})
    print('install', 'UNEXPECTED_OK')
except Exception as exc:
    print('install', type(exc).__name__, exc)
try:
    bootstrap_control_plane({str(jobops_home)!r})
    print('bootstrap', 'UNEXPECTED_OK')
except Exception as exc:
    print('bootstrap', type(exc).__name__, exc)
try:
    ControlPlaneController({str(jobops_home)!r})
    print('controller', 'UNEXPECTED_OK')
except Exception as exc:
    print('controller', type(exc).__name__, exc)
raise SystemExit(0)
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "UNEXPECTED_OK" not in proc.stdout
    assert "AuthorityError" in proc.stdout
