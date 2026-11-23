# Harness contract — jobsOps

`./run` (or `jobops run`) orchestrates **F01 context**, **HTTP-only discovery workers** (lane × country, parallel), **merge + ledger**, **F03 verify**, **F04 rank**, a **frontier rank-report** agent (optional gated submit), **validate**, **F10 report enrich + Sheets/Drive offline adapters**, optional **F07 pipeline / F06 outreach / F08 learning**, and **ledger finalize**.

Agents are invoked through `lib/agent_runtime.py` (`JOBOPS_RUNTIME=auto|cursor|claude_code|codex|antigravity|deterministic`). Unrestricted `--force --trust` is forbidden. Failed/timed-out workers set `exhausted: false`.

**Pipeline-only mode** skips discovery: `./run --pipeline-only` or `JOBOPS_MODE=pipeline`. Requires explicit `PIPELINE_INBOX` (test fixtures are not live defaults).

## Pipeline (full)

```text
context → exclusion → workers → merge → verify → rank → frontier → validate
  → report_enrich → sheets_sync → drive_folders
  → (optional inbox skim / outreach drafts / learning batch)
  → ledger_finalize
```

## Pipeline-only

```text
context → inbox_outcomes (P01) → report_enrich → sheets_sync → drive_folders → ledger_finalize
```

1. **Context (F01 lite)** — `lib/run_context.py` writes `runs/<id>/run-context.json` + `session-inventory.json`, inserts the run row, acquires the run lock in `state/jobops.db`. Abort if lock cannot be acquired.
2. Build `exclusion-index.json` from `_sheet_exports` (best-effort); reconcile counts into run-context. *(Skipped in pipeline-only.)*
3. Run workers in `workers/manifest.json` **in parallel** when `parallel: true` and `mode: http`. *(Skipped in pipeline-only.)*
4. Each worker targets **15** matches (`target_matches`), writes `runs/<run_id>/shards/<shard_id>.json` only, then exits. Matches require non-empty `reason` + `evidence_quote`.
5. Ledger ingests shards as `discovered_job` artifacts.
6. `lib/merge_shards.py` merges shards → `handoff-state.json` (backward compatible). Harness attaches `eligible_count`.
7. Ledger checkpoints merge (`handoff_match` / `handoff_state` artifacts).
8. **Verify (F03)** — `lib/verify_jobs.py` after merge: V01 availability, V04 duplicates, V02/V03 hard-miss + sponsorship. Writes `EligibilityDecision` artifacts; enriches match statuses. Optional thin agent when `VERIFY_AGENT=1`.
9. **Rank (F04)** — `lib/rank_opportunities.py` (I01–I04) after verify, before frontier. Writes `runs/<id>/ranked-shortlist.json` (top-5 Eligible + Needs review human queue). No fictional % certainty.
10. **Frontier rank-report** — `agents/frontier-rank-report.md` every run. HTTP expand (`frontier-expand.json`, ≤20) only if floor unmet; harness re-merges, re-verifies, re-ranks. Optional **frontier-submit** only when `SUBMIT_AGENT=1` **and** `JOBOPS_ALLOW_SUBMIT=1` **and** `JOBOPS_ENABLE_LIVE_SUBMIT=1` **and** authorize `--check-only` allows. Authorize ignores agent checklist booleans; requires independent evidence objects.
11. Validator accepts when floor met **or** honest exhaustion; requires `last-run-report.md`; emits `eligible_count`.
12. **Report enrich (R03/R04)** — `lib/run_report.py` writes `run-metrics.json` + `reliability-alerts.json` and appends Phase 4 metrics to the report (eligible_count, verify stats, wall time hooks, stubbed workers, cap remaining; stuck locks / missing receipts).
13. **Sheets sync plan (R01)** — `lib/sheets_sync.py` writes idempotent offline plans (`integration=offline_plan`, `live_api=false`). Live Google Sheets API is **not** implemented.
14. **Drive folders (R02)** — `lib/drive_artifacts.py` ensures **local mirror** folders by `job_key` (`live_drive_api=false`). Live Google Drive API is **not** implemented.
15. **Optional event slices** (not concurrent LLM frontiers):
    - `PIPELINE_INBOX=...` (required path; never defaults to `evals/fixtures`) → P01 inbox skim
    - `OUTREACH_DRAFTS=1` + candidates → draft-only F06; **no auto-send** (`JOBOPS_ENABLE_OUTREACH_SEND` default 0)
    - `LEARNING_BATCH=1` → F08 proposals; **never mutates policy**
16. Ledger finalize — mark run complete, release run lock.

## Speed defaults

| Knob | Default | Override |
|---|---|---|
| Worker target | 15 | `workers/manifest.json` `target_matches` |
| Parallel HTTP | on | `parallel: false` for sequential |
| Discovery floor | 40 | `HANDOFF_FLOOR=100` |
| Worker timeout | 720s | `WORKER_TIMEOUT_SEC` |
| Ledger DB | `state/jobops.db` | `JOBOPS_DB` |
| Verify agent | off | `VERIFY_AGENT=1` |
| Submit agent | off | `SUBMIT_AGENT=1` + `JOBOPS_ALLOW_SUBMIT=1` + `JOBOPS_ENABLE_LIVE_SUBMIT=1` |
| Runtime | `auto` | `JOBOPS_RUNTIME=cursor\|claude_code\|codex\|antigravity\|deterministic` |
| JobOps mode | `full` | `JOBOPS_MODE=pipeline` or `./run --pipeline-only` |
| Pipeline inbox | unset (must set explicitly) | `PIPELINE_INBOX` (fixtures refused) |
| Outreach drafts | off | `OUTREACH_DRAFTS=1` |
| Learning batch | off | `LEARNING_BATCH=1` |

Submit cap remains **1**. Floor is discovery volume for handoff, not a submit quota. `HANDOFF_FLOOR` default **40**.

## Contracts (`contracts/`)

| Schema | Role |
|---|---|
| `envelope.schema.json` | Universal event envelope |
| `run-context.schema.json` | F01 RunContext |
| `discovered-job.schema.json` | Worker match payload |
| `eligibility-decision.schema.json` | Verification decision |
| `ranked-opportunity.schema.json` | F04 ranked shortlist item |
| `application-package.schema.json` | F05 materials + authorize state |
| `submission-receipt.schema.json` | Submit outcome / receipt |
| `outcome-event.schema.json` | F07 P01 inbox outcome |
| `learning-event.schema.json` | F08 learning proposal |
| `experiment-proposal.schema.json` | F08 A/B experiment proposal |
| `outreach-draft.schema.json` | F06 draft-only outreach |
| `handoff-state.schema.json` | Merged handoff state |

Validate: `python3 lib/contracts.py <schema-name> <file.json>`

Envelope fields (locked): `schema_version`, `event_id`, `run_id`, `job_key`, `task_id`, `producer`, `artifact_type`, `created_at`, `policy_version`, `trace_id`, `status`, `payload`, `evidence_refs`, `blocking_reasons`, `retryable`.

## Worker shard schema

Path: `runs/<run_id>/shards/<shard_id>.json`

```json
{
  "shard_id": "fde-de",
  "run_id": "YYYYMMDD-HHMMIST",
  "lane": 1,
  "lane_name": "forward-deployed",
  "country": "Germany",
  "mode": "http",
  "exhausted": false,
  "sources_tried": ["GermanTechJobs"],
  "sources_blocked": [{"source": "Indeed", "reason": "JS/CAPTCHA"}],
  "sources_remaining_readable": [],
  "matches": [
    {
      "canonical_url": "https://jobs.example.com/req/1",
      "employer_or_ats_url": "https://jobs.example.com/req/1",
      "organization": "Example",
      "role": "Forward Deployed Engineer",
      "status": "Needs review",
      "lane": 1,
      "country": "Germany",
      "source": "Ashby",
      "reason": "Sponsorship not evidenced"
    }
  ]
}
```

Workers must **not** write `handoff-state.json` or `last-run-report.md`, must **not** submit, and must **not** use a browser. Every match **must** include non-empty `reason` and non-empty `evidence_quote`. Prefer Greenhouse / Ashby / Lever HTTP APIs in `preferred_sources`.

## `handoff-state.json`

Produced by `merge_shards.py` (still the backward-compatible handoff file):

- `floor` = harness `HANDOFF_FLOOR` (default 40)
- `cumulative_handoff_matches` == `matches.length`
- `floor_met` iff cumulative ≥ floor
- `eligible_count` — attached by harness after merge / verify
- `ranking` — attached by `rank_opportunities.py`
- unique `canonical_url`s
- exhaustion requires non-empty `sources_tried` and empty `sources_remaining_readable`

Validate: `python3 lib/validate_handoff_state.py handoff-state.json [floor]`

## Ledger (`lib/ledger.py` → `state/jobops.db`)

SQLite WAL tables: `runs`, `artifacts`, `jobs`, `task_attempts`, `locks`, `audit_events`.

Helpers: `append_artifact`, `transition_job`, `acquire_lock`, `release_lock`. Idempotency via unique `event_id` and `(job_key, artifact_type, content_hash)`.

`state/` is gitignored. Crash restart can skip completed `task_id`s via `task_attempts`.

## Policy & evals

- `lib/policy.py` — verified-fact denylist, tool permissions by role, daily cap=1, floor, SOP §15 + Phase 3 authorize states, E05/E06/adversarial gates. **Never auto-mutated by F08.**
- `lib/verify_jobs.py` — F03 V01–V04; `agents/verification.md` thin agent for ambiguous sponsorship JSON only.
- `lib/rank_opportunities.py` — F04 I01–I04; top-5 shortlist.
- `lib/submission_authorize.py` — F09 gate (ATS≥80, quality≥75, fingerprint, lock, cap, checklist). Never auto-retry after `SubmissionUncertain`.
- `lib/inbox_outcomes.py` — P01 classify + reconcile; P02–P04 stubs.
- `lib/sheets_sync.py` / `lib/drive_artifacts.py` — R01/R02 offline-safe adapters.
- `lib/run_report.py` — R03/R04 metrics + alerts.
- `lib/learning_proposals.py` — L01–L04 proposal-only.
- `lib/outreach_drafts.py` — O01–O04 draft-only; `agents/outreach-draft.md`.
- Fixtures: `evals/fixtures/{e01…e12,adversarial,rank}/`
- Tests: `python3 -m pytest tests/ -q`

## Frontier

- **Rank-report** (default): report first; consume ranked shortlist; no browser submit.
- **Submit** (optional): at most one submit after authorize; no re-crawl of worker boards.
- May write `frontier-expand.json` (HTTP only, ≤20) if floor unmet.
- Must write `last-run-report.md` with handoff vs floor and: no quota was promised, and no unverified submission was recorded.
- Compat redirect: `agents/frontier.md` → split prompts.

## Hard rules (Phase 4)

- No outreach auto-send
- No auto policy writes
- Event-triggered slices only (not 10 concurrent LLM frontiers)
- Live Gmail/Sheets optional; skipped when credentials missing
