# Runtime adapter capabilities

**Status:** Detect + smoke only unless noted. Not production-certified for unattended submit. **Live automatic submission remains disabled.**

| Provider | Detect | build_argv smoke | Unattended invoke | ToolBroker seal | Minimal agent env | OS sandbox of child CLI | Notes |
|---|---|---|---|---|---|---|---|
| deterministic | yes | n/a (no spawn) | skips agent | yes | n/a | n/a | Default when no CLI found |
| cursor (`agent` / `cursor-agent`) | PATH detect | `--print` only; refuses `--force/--trust` | **fail closed** unless unsandboxed opt-in (non-sensitive roles only) | yes (pre-spawn) | yes (allowlist; no `JOBOPS_HOME`/`PYTHONPATH`/control-plane) | **unsupported** | Allowlist embedded as prompt hint only |
| claude_code (`claude`) | PATH detect | `-p` print mode | **fail closed** (same) | yes | yes | **unsupported** | Verify installed CLI flags per version |
| codex (`codex`) | PATH detect | `exec` argv shape | **fail closed** (same) | yes | yes | **unsupported** | `--skip-git-repo-check` only; no trust bypass |
| antigravity (`antigravity` / `agy`) | PATH detect | `run --prompt` | **unsupported** / fail closed | yes | yes | **unsupported** | Confirm CLI before any automation |
| ChatGPT chat | n/a | n/a | **unsupported** | n/a | n/a | n/a | Not a local scheduler |

## What is enforced vs informational
- **Enforced:**
  - `ToolBroker` / `resolve_allowed_tools` at jobsOps invoke
  - `AgentSandbox` for jobsOps-mediated FS/network/process tool handlers
  - Minimal subprocess env (`build_agent_subprocess_env`) — no evidence/approval/connector secrets, no `JOBOPS_HOME` / `PYTHONPATH` / `JOBOPS_CONTROL_PLANE`
  - Fail closed when third-party CLI restrictions cannot be verified; **sensitive roles (`frontier_submit`, `outreach`) never allow unsandboxed opt-in**
  - Privileged tools only for `frontier_submit`; submit kill switches
  - `ControlPlaneController` signed `AuthorityGrant` required for `OrchestratorContext`
  - Interactive `InteractiveApprovalGate` → MAC'd `ConfirmationReceipt` → stored single-use `UserSession` (production TTY only; synthetic channels need authenticated test config)
  - Control plane requires pre-provisioned OS-openable `secrets/control_plane.privilege` (mode 0600; `jobops control-plane provision`) — env flag alone fails closed; approve never auto-installs
  - HMAC evidence + durable approvals; approve bind/consume/decide is atomic (`BEGIN IMMEDIATE`)
  - Permanent `application_identities` guard across dates/runs; atomic `submission_reservations` **required** before authorize; consume on Applied/Submitted; `uncertain` blocks retry
  - Cross-process SQLite reservation / daily-cap serialization (`BEGIN IMMEDIATE`)
  - SSRF pin on `url_safety.safe_http_fetch` (sole outbound HTTP policy)
- **Informational only:** `JOBOPS_ALLOWED_TOOLS` env and `[jobops-tool-allowlist …]` prompt headers. Child CLIs may ignore them; jobsOps must not dispatch tools except through the broker/sandbox.

## Implemented vs not yet supported

| Capability | Implemented | Not yet supported |
|---|---|---|
| Minimal agent env allowlist | yes (strips home/path/control-plane) | — |
| Broker + sandbox tool FS/network/process gates | yes (jobsOps-mediated) | OS seccomp/container for vendor CLIs |
| Trusted session issuer + stored single-use sessions | yes (`InteractiveApprovalGate` + MAC receipts) | Rich UI approval inbox / SSO / WebAuthn |
| Protected control-plane authority issuer | yes (`ControlPlaneController` + OS privilege credential) | HSM / hardware key store / separate privileged daemon |
| Orchestrator-gated evidence issuance | yes | Hardware-backed isolation from same OS user |
| Atomic daily submit reservations + consume/uncertain | yes | Distributed multi-host coordinator |
| Unsandboxed AI blocked for sensitive workflows | yes | OS sandbox for discovery/rank CLIs |
| Cross-process concurrency tests | yes | Multi-host soak / chaos |
| Real PDF fixture + ordered extract | yes | Full ATS visual QA / LaTeX pipeline |
| Mock ATS form→confirm→timeout→duplicate | yes (in-process) | Live browser portal adapters |
| Unified outbound HTTP safety | yes (`safe_http_fetch`) | Dedicated egress proxy |
| Live automatic submission | **disabled by default** | Production-certified auto-submit |

## Smoke commands
```bash
python -c "from agent_runtime import detect_all; import json; print(json.dumps([r.to_dict() for r in detect_all()], indent=2))"
python -m pytest tests/test_agent_runtime.py tests/test_trust_boundary_remediation.py tests/test_authority_session_p0.py tests/test_reservation_concurrency_p1.py -q
```

Unavailable CLIs are skipped with an explicit unsupported reason — never claimed as passing.
