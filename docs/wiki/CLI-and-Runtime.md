# CLI & Runtime

Verified against the installed entry point `jobops = jobops.cli:main` and the `./run` harness script.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Requires Python **≥ 3.10** (`pyproject.toml`).

## Commands

| Command | Purpose |
|---|---|
| `jobops init` | Create private workspace + candidate profile |
| `jobops doctor` | Check workspace, runtimes, defaults |
| `jobops run` | Invoke the local harness |
| `jobops report` | Summarize latest run artifacts |
| `jobops approve` | Interactive TTY approval (privilege must already exist) |
| `jobops control-plane provision` | Explicit privilege credential install only |

### `jobops run` flags

| Flag | Behavior |
|---|---|
| `--workflow {discovery,daily-search,pipeline,applications,inbox-reconcile}` | Workflow selection |
| `--preview` | **Non-mutating** plan: prints what would run; no harness / ledger writes |
| `--dry-run` | Forces submit/outreach off; harness **may** still write local ledger/handoff/report |
| `--pipeline-only` | Skip discovery; inbox → report path |
| `--inbox PATH` | Explicit inbox path (never silently default to test fixtures for live runs) |
| `--workspace PATH` | Override `JOBOPS_HOME` |
| `--runtime NAME` | Override `JOBOPS_RUNTIME` |

Equivalent harness entry: `./run` (zsh). Modes: full (default) or `--pipeline-only`.

## Environment kill switches

```bash
# Required together for any live submit path (still subject to authorize + reservation)
JOBOPS_ALLOW_SUBMIT=1
JOBOPS_ENABLE_LIVE_SUBMIT=1
SUBMIT_AGENT=1

# Outreach send (separate from drafts)
JOBOPS_ENABLE_OUTREACH_SEND=0   # default
```

Evidence secret: set `JOBOPS_EVIDENCE_SECRET` or place a key at `JOBOPS_HOME/secrets/evidence_hmac.key`. **No fallback secret.**

## Tests

```bash
python -m pytest -q
```

CI also loads every `contracts/*.schema.json` and runs a CLI smoke (`init` / `doctor`) with submit flags forced off.

## User guide

Longer install/schedule UX notes: [USER-GUIDE.md](../USER-GUIDE.md). Harness stage contract: [harness-contract.md](../../harness-contract.md).
