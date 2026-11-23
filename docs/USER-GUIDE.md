# User guide: installation, manual, scheduled and event-triggered runs

**Status:** Foundation CLI implemented (`jobops init|doctor|report|run` + `jobops control-plane provision`). Schedule/event watchers remain target UX. External submit/outreach send stay off by default. Mergeable foundation only — **not** a certified production release / not production-ready. `jobops init` never installs control-plane credentials; operators must run `jobops control-plane provision` explicitly.

## The universal path

1. Install a tagged release from `https://github.com/AnkitParekh007/jobsOps` and verify source and requirements.
2. Create local virtual environment, install package.
3. Run `jobops init`; import verified resume; choose role families, locations, compensation, work rights, sponsorship and remote/travel constraints.
4. Choose provider: Claude Code, Codex CLI, Cursor Agent CLI, Antigravity if suitable, direct model API or deterministic-only mode.
5. Configure required public sources, and optional email/Sheets/Drive/calendar/browser integrations.
6. Choose research-only, prepare-for-review (default), or separately authorized controlled submission; set quota and consent restrictions.
7. Run `jobops doctor`, then prefer `jobops run --workflow discovery --preview` for a
   **non-mutating** plan (no harness, no ledger/handoff writes).
   Use `--dry-run` only when you intentionally want the harness to run with external
   submit/outreach disabled — local ledger/handoff/report files may still be written.
8. Run `jobops run --workflow daily-search`; inspect `jobops report`, approvals and evidence.
9. Optionally enable scheduling or supported event watchers. Verify a run persisted on restart.

```bash
git clone https://github.com/AnkitParekh007/jobsOps.git
cd jobsOps
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
jobops init
jobops doctor
jobops run --workflow discovery --preview
jobops run --workflow discovery --dry-run
jobops run --workflow daily-search
jobops report
```

Provision an installation-specific evidence key before any authorize path outside tests:
`export JOBOPS_EVIDENCE_SECRET="$(openssl rand -hex 32)"` or write
`$JOBOPS_HOME/secrets/evidence_hmac.key` (mode `0600`). There is no built-in fallback secret.


Windows activation: `.venv\Scripts\activate`. Documentation must be updated when actual installation and commands are tested.

## AI platform comparison
| Platform | User interaction | Proposed integration | Unattended option / limitations |
|---|---|---|---|
| Claude Code | Open repository, invoke Claude | CLAUDE.md + AGENTS.md + CLI, optional skills | JobOps scheduler invokes supported CLI/API adapter; credentials and plan restrictions apply |
| Codex | Open repository with Codex CLI/app | AGENTS.md + CLI, optional MCP | JobOps scheduler + supported noninteractive adapter; chat session is not scheduler |
| Cursor | Open repo in IDE, use Agent | .cursor/rules + CLI, optional agent CLI | Local scheduler or supported Cursor Automations; cloud cannot magically read Mac secrets |
| Antigravity | Open repository in supported IDE/CLI | .agent/workflows + AGENTS.md + CLI | Verify current installed CLI/API support; local JobOps scheduler is baseline |
| ChatGPT | Natural-language front end | Future authenticated app/MCP/remote API | Chat conversation alone cannot access local process or act as always-on local scheduler |
| Other | CLI or supported agent tool | Universal CLI, skill or MCP | Capabilities and authentication must be probed and documented |

Do not claim universal native schedules, tool permissions or chat integration. Detect and report unsupported adapters clearly.

## Manual
```bash
jobops run --workflow discovery
jobops run --workflow applications --mode prepare
jobops run --workflow inbox-reconcile
jobops report
```

## Schedule
```yaml
schedule:
  name: daily-job-search
  workflow: daily-search
  timezone: Asia/Kolkata
  cron: "0 9,21 * * *"
  mode: prepare
  enabled: false
```

```bash
jobops schedule enable daily-job-search
jobops schedule list
jobops schedule disable daily-job-search
```

The schedule above is an example only. Never commit the personal user's actual calendar, resume, credentials or IDs. Local schedules require the machine to be running; optionally support launchd, systemd and Windows Task Scheduler. Cloud scheduling needs secure remote state and explicit connector authorization.

## Event workflows
- New verified candidate → verify/rank.
- Gmail application receipt → reconcile; append only if identity confirmed.
- Rejection → factual OutcomeEvent (not speculative cause).
- Interview invitation → interview brief and schedule task.
- Deadline approaching → reminder.
- Follow-up due → draft (no send by default).
- Application approval → recheck eligibility, cap, live status, session then submit if permitted.

Deduplicate by external event ID and use a durable queue. Do not reuse events for duplicate external sends.

## Client example prompt

> Read AGENTS.md, inspect the actual jobsOps installation, and run the daily-search workflow through the installed CLI. Use verified candidate context, check live employer/ATS sources and dedupe prior jobs. Update the local tracker and give me the run ID, eligible queue and blockers. Do not change source code, claim unsupported commands exist, submit an application, or send a message unless jobsOps policy explicitly authorizes it.

## What users should see
- Run ID, start/end, policy and agent adapter versions.
- Sources attempted, blocked, exhausted (with proof), jobs discovered, verified, eligible, skipped, unresolved.
- Ready-for-review packages, submissions with receipts, uncertain attempts awaiting reconciliation.
- Tracker/Drive/email sync status, errors, retry queue, cost/time and next action.
- No guarantees that discovery yields eligible roles or that a provider can submit on every ATS portal.
