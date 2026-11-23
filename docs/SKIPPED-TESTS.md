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

`test_provider_adapter_smoke[deterministic]` always runs (no external CLI).

## Implemented vs future integration work

| Area | Implemented now | Future / not claimed |
|---|---|---|
| Tool permission broker | `lib/tool_broker.py` sealed scopes | OS-level sandbox of third-party agent CLIs |
| Evidence HMAC + approvals | Fail-closed secret; ledger `approvals` | Hardware-backed key store / HSM |
| PDF live validation | Recompute + magic + reject fixtures | Full ATS visual QA |
| SSRF / DNS rebinding | Validate + pin IP + peer check | Dedicated egress proxy |
| Preview mode | `jobops run --preview` non-mutating | Rich UI approval inbox |
| Mock portal E2E | In-process authorize/receipt simulation | Live browser portal adapters (opt-in) |
| Sheets/Drive | Offline plan artifacts | Authenticated live Google APIs |
| Provider adapters | Detect + argv smoke | Certified unattended multi-hour runs |

CI green with skips means: deterministic suite passed; missing CLIs were labeled unsupported, not faked.
