---
name: jobops
description: Route jobsOps work through the installed CLI and policy engine. Never invent engines, submissions, or eligibility.
---

# jobsOps skill router

1. Read `AGENTS.md` and inspect the local installation (`jobops doctor` or `python -m jobops.cli doctor`).
2. Use verified candidate context from the private `JOBOPS_HOME` workspace only.
3. Prefer deterministic CLI stages (`jobops run`, `lib/*.py`) over improvising evaluation results.
4. Do **not** submit applications or send outreach unless policy + consent + `JOBOPS_ALLOW_SUBMIT` / `JOBOPS_ENABLE_LIVE_SUBMIT` explicitly authorize it.
5. If a command or adapter is unsupported, say so clearly — never fabricate success, exhaustion, or Applied status.
6. A worker timeout is not source exhaustion.

```bash
python -m pip install -e .
jobops init
jobops doctor
jobops run --workflow discovery --dry-run
jobops report
```
