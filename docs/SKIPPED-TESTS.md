# Skipped tests — what they mean

Pytest may skip provider adapter smokes when a CLI binary is not on `PATH`. Skips are **not** silent passes.

## Typical skip sources (up to ~5 on a clean CI/dev host)

| Test | When skipped | Meaning |
|---|---|---|
| `test_cursor_argv_never_includes_force_trust` | `agent` / `cursor-agent` missing | Cursor adapter not installed on this host |
| `test_provider_adapter_smoke[cursor]` | Cursor CLI missing | Unsupported here; notes explain why |
| `test_provider_adapter_smoke[claude_code]` | `claude` missing | Unsupported here |
| `test_provider_adapter_smoke[codex]` | `codex` missing | Unsupported here |
| `test_provider_adapter_smoke[antigravity]` | Antigravity CLI missing | Unsupported here |
| `test_cursor_invoke_fails_closed_without_unsandboxed_opt_in` | may early-return via restriction helper when CLI missing | Still asserts fail-closed policy |

`test_provider_adapter_smoke[deterministic]` always runs (no external CLI).

## Implemented vs future integration work

| Area | Implemented now | Future / not claimed |
|---|---|---|
| Tool permission broker | `lib/tool_broker.py` sealed scopes | — |
| Agent sandbox (FS/net/process) | `lib/agent_sandbox.py` for broker tools | OS-level sandbox of third-party agent CLIs |
| Minimal agent env | `lib/trust_boundary.build_agent_subprocess_env` | — |
| Fail-closed unsandboxed CLIs | default refuse; opt-in `JOBOPS_ALLOW_UNSANDBOXED_AGENT=1` | Verified vendor sandbox APIs |
| Evidence HMAC + approvals | Fail-closed secret; `ApprovalController` pending→approve; `OrchestratorContext` | Hardware-backed key store / HSM |
| PDF live validation | Recompute + magic + reject fixtures; `pdf_fixture` ordered extract | Full ATS visual QA |
| SSRF / DNS rebinding | Validate + pin IP + peer check | Dedicated egress proxy |
| Atomic daily reservations | `submission_reservations` + `BEGIN IMMEDIATE` | Multi-host distributed lock service |
| Preview mode | `jobops run --preview` non-mutating | Rich UI approval inbox |
| Mock portal / ATS E2E | Authorize/receipt + form/confirm/timeout/duplicate | Live browser portal adapters (opt-in) |
| Sheets/Drive | Offline plan artifacts | Authenticated live Google APIs |
| Provider adapters | Detect + argv smoke | Certified unattended multi-hour runs |
| Live auto-submit | **Intentionally disabled** | Production-certified auto-submit |

CI green with skips means: deterministic suite passed; missing CLIs were labeled unsupported, not faked.
