# Runtime adapter capabilities

**Status:** Detect + smoke only unless noted. Not production-certified for unattended submit.

| Provider | Detect | build_argv smoke | Unattended invoke | ToolBroker seal | OS sandbox of child CLI | Notes |
|---|---|---|---|---|---|---|
| deterministic | yes | n/a (no spawn) | skips agent | yes | n/a | Default when no CLI found |
| cursor (`agent` / `cursor-agent`) | PATH detect | `--print` only; refuses `--force/--trust` | not certified | yes (pre-spawn) | **unsupported** | Allowlist embedded as prompt hint only |
| claude_code (`claude`) | PATH detect | `-p` print mode | not certified | yes | **unsupported** | Verify installed CLI flags per version |
| codex (`codex`) | PATH detect | `exec` argv shape | not certified | yes | **unsupported** | `--skip-git-repo-check` only; no trust bypass |
| antigravity (`antigravity` / `agy`) | PATH detect | `run --prompt` | **unsupported** (`supports_noninteractive=false`) | yes | **unsupported** | Confirm CLI before any automation |
| ChatGPT chat | n/a | n/a | **unsupported** | n/a | n/a | Not a local scheduler |

## What is enforced vs informational
- **Enforced:** `ToolBroker` / `resolve_allowed_tools` at jobsOps invoke; privileged tools only for `frontier_submit`; submit kill switches; HMAC evidence + durable approvals; SSRF pin on `url_safety.safe_http_fetch`.
- **Informational only:** `JOBOPS_ALLOWED_TOOLS` env and `[jobops-tool-allowlist …]` prompt headers. Child CLIs may ignore them; jobsOps must not dispatch tools except through the broker.

## Smoke commands
```bash
python -c "from agent_runtime import detect_all; import json; print(json.dumps([r.to_dict() for r in detect_all()], indent=2))"
python -m pytest tests/test_agent_runtime.py -q
```

Unavailable CLIs are skipped with an explicit unsupported reason — never claimed as passing.
