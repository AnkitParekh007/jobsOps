# Runtime adapter capabilities

**Status:** Detect + smoke only unless noted. Not production-certified for unattended submit.

| Provider | Detect | build_argv smoke | Unattended invoke | ToolBroker seal | Minimal agent env | OS sandbox of child CLI | Notes |
|---|---|---|---|---|---|---|---|
| deterministic | yes | n/a (no spawn) | skips agent | yes | n/a | n/a | Default when no CLI found |
| cursor (`agent` / `cursor-agent`) | PATH detect | `--print` only; refuses `--force/--trust` | **fail closed** unless `JOBOPS_ALLOW_UNSANDBOXED_AGENT=1` | yes (pre-spawn) | yes (allowlist) | **unsupported** | Allowlist embedded as prompt hint only |
| claude_code (`claude`) | PATH detect | `-p` print mode | **fail closed** (same opt-in) | yes | yes | **unsupported** | Verify installed CLI flags per version |
| codex (`codex`) | PATH detect | `exec` argv shape | **fail closed** (same opt-in) | yes | yes | **unsupported** | `--skip-git-repo-check` only; no trust bypass |
| antigravity (`antigravity` / `agy`) | PATH detect | `run --prompt` | **unsupported** / fail closed | yes | yes | **unsupported** | Confirm CLI before any automation |
| ChatGPT chat | n/a | n/a | **unsupported** | n/a | n/a | n/a | Not a local scheduler |

## What is enforced vs informational
- **Enforced:**
  - `ToolBroker` / `resolve_allowed_tools` at jobsOps invoke
  - `AgentSandbox` for jobsOps-mediated FS/network/process tool handlers
  - Minimal subprocess env (`build_agent_subprocess_env`) — no evidence/approval/connector secrets
  - Fail closed when third-party CLI restrictions cannot be verified (unless unsandboxed opt-in)
  - Privileged tools only for `frontier_submit`; submit kill switches
  - HMAC evidence + `ApprovalController` (pending → authenticated approve) + `OrchestratorContext`
  - Atomic `submission_reservations` for daily cap across processes
  - SSRF pin on `url_safety.safe_http_fetch` (sole outbound HTTP policy)
- **Informational only:** `JOBOPS_ALLOWED_TOOLS` env and `[jobops-tool-allowlist …]` prompt headers. Child CLIs may ignore them; jobsOps must not dispatch tools except through the broker/sandbox.

## Implemented vs not yet supported

| Capability | Implemented | Not yet supported |
|---|---|---|
| Minimal agent env allowlist | yes | — |
| Broker + sandbox tool FS/network/process gates | yes (jobsOps-mediated) | OS seccomp/container for vendor CLIs |
| Authenticated approval controller | yes | Rich UI approval inbox / SSO |
| Orchestrator-gated evidence issuance | yes | HSM / hardware key store |
| Atomic daily submit reservations | yes | Distributed multi-host coordinator |
| Real PDF fixture + ordered extract | yes | Full ATS visual QA / LaTeX pipeline |
| Mock ATS form→confirm→timeout→duplicate | yes (in-process) | Live browser portal adapters |
| Unified outbound HTTP safety | yes (`safe_http_fetch`) | Dedicated egress proxy |
| Live automatic submission | **disabled by default** | Production-certified auto-submit |

## Smoke commands
```bash
python -c "from agent_runtime import detect_all; import json; print(json.dumps([r.to_dict() for r in detect_all()], indent=2))"
python -m pytest tests/test_agent_runtime.py tests/test_trust_boundary_remediation.py -q
```

Unavailable CLIs are skipped with an explicit unsupported reason — never claimed as passing.
