# Provider Adapters / Compatibility Matrix

Set `JOBOPS_RUNTIME` to `auto`, `cursor`, `claude_code`, `codex`, `antigravity`, or `deterministic`.

**Status:** Detect + smoke unless noted. Not production-certified for unattended submit. Live automatic submission remains disabled.

| Provider | Detect | Unattended invoke | Notes |
|---|---|---|---|
| `deterministic` | yes | skips agent | Default when no CLI found; core paths work without AI |
| `cursor` | PATH (`agent` / `cursor-agent`) | Fail closed unless unsandboxed opt-in (non-sensitive roles) | Refuses `--force` / `--trust` |
| `claude_code` | PATH (`claude`) | Fail closed (same) | Verify flags per CLI version |
| `codex` | PATH (`codex`) | Fail closed (same) | No trust bypass |
| `antigravity` | PATH (`antigravity` / `agy`) | Unsupported / fail closed | Confirm CLI before automation |
| ChatGPT chat | n/a | Unsupported | Not a local scheduler |

## Enforced vs informational

**Enforced by jobsOps:** ToolBroker allowlists, AgentSandbox for mediated tools, minimal agent subprocess env (secrets / `JOBOPS_HOME` / control-plane stripped), dual submit kill switches, control-plane grants, interactive approval, atomic reservations, SSRF-safe HTTP.

**Informational only:** `JOBOPS_ALLOWED_TOOLS` env and prompt allowlist headers — child CLIs may ignore them.

Sensitive roles (`frontier_submit`, `outreach`) **never** allow unsandboxed opt-in.

## Smoke

```bash
python -c "from agent_runtime import detect_all; import json; print(json.dumps([r.to_dict() for r in detect_all()], indent=2))"
```

Unavailable CLIs are reported as unsupported — never claimed as passing. Full matrix: [RUNTIME-CAPABILITIES.md](../RUNTIME-CAPABILITIES.md).
