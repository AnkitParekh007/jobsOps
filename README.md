# jobsOps

Provider-neutral, policy-governed job search operations. Discovery, verification, ranking, and optional controlled submission run through a deterministic harness — not a single-vendor prompt.

**Status:** mergeable foundation in progress — **not** a certified production release. Not production-ready. External submit and outreach send are **off by default**.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
jobops init
jobops doctor
jobops run --workflow discovery --preview   # non-mutating plan (no harness)
jobops run --workflow discovery --dry-run   # harness runs; submit/outreach off; local state may update
# Set JOBOPS_EVIDENCE_SECRET (or JOBOPS_HOME/secrets/evidence_hmac.key) — no fallback secret
# See docs/THREAT-MODEL.md and docs/RUNTIME-CAPABILITIES.md
jobops report
```

Private candidate facts live under `JOBOPS_HOME` (OS-appropriate Application Support / XDG path), **outside** this repository.

## Runtime adapters

Set `JOBOPS_RUNTIME` to one of: `auto`, `cursor`, `claude_code`, `codex`, `antigravity`, `deterministic`.

The harness never passes unrestricted `--force --trust`. Submit requires explicit:

```bash
JOBOPS_ALLOW_SUBMIT=1 JOBOPS_ENABLE_LIVE_SUBMIT=1 SUBMIT_AGENT=1
```

## Docs

- [AGENTS.md](AGENTS.md) — agent authority and constraints
- [docs/USER-GUIDE.md](docs/USER-GUIDE.md) — install / schedule UX
- [docs/PRODUCTION-READINESS.md](docs/PRODUCTION-READINESS.md) — audit rubric (not a certification)
- [harness-contract.md](harness-contract.md) — `./run` contract

## Tests

```bash
python -m pytest -q
```
