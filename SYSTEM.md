# jobsOps — system overview

Provider-neutral job-search operations harness. Quality and evidence beat volume. Candidate facts load from the private `JOBOPS_HOME` workspace — never hardcoded personal biography in the public repo. External submit and outreach send remain **off by default**.

Related contracts: `harness-contract.md`, `docs/USER-GUIDE.md`, `agents/*.md`, `workers/manifest.json`, `contracts/*.schema.json`.

**Not production-ready.** See `docs/PRODUCTION-READINESS.md`.

---

## 1. Frontier agents and sub-agents

### Count (current MVP)

| Role | Count per run | How launched | Prompt |
|---|---:|---|---|
| **Frontier rank-report** | **1** (plus optional **finish** re-invoke) | Sequential after rank | `agents/frontier-rank-report.md` (+ SOP appended) |
| **Frontier submit** | **0–1** | Only if `SUBMIT_AGENT=1` **and** `JOBOPS_ALLOW_SUBMIT=1` **and** `JOBOPS_ENABLE_LIVE_SUBMIT=1` **and** authorize `--check-only` allows | `agents/frontier-submit.md` |
| **Discovery workers (sub-agents)** | **3** (manifest-driven) | Parallel HTTP by default | `agents/discovery-worker.md` + per-shard inject |
| **Verification (thin, optional)** | **0–1** | When `VERIFY_AGENT=1` and ambiguous sponsorship queue non-empty | `agents/verification.md` |
| **Outreach drafts (optional)** | **0–1** | When `OUTREACH_DRAFTS=1` + candidates JSON | `agents/outreach-draft.md` |

Deterministic stages: `lib/verify_jobs.py`, `lib/rank_opportunities.py`, `lib/submission_authorize.py`, `lib/inbox_outcomes.py`, `lib/sheets_sync.py`, `lib/drive_artifacts.py`, `lib/learning_proposals.py`, `lib/run_report.py`, `lib/outreach_drafts.py`. `agents/frontier.md` is a thin redirect to the split prompts.

**Constraint:** event-triggered slices only — do not stand up 10 concurrent LLM frontiers.

### Current worker shards (`workers/manifest.json` v2)

| `shard_id` | Lane | Country | Target matches |
|---|---|---|---:|
| `fde-de` | 1 · forward-deployed | Germany | 15 |
| `frontend-de` | 2 · frontend-architecture | Germany | 15 |
| `fde-ie` | 1 · forward-deployed | Ireland | 15 |

### Mental model

```text
┌─────────────────────────────────────────────────────────────┐
│  ./run  (zsh harness — not an LLM)                          │
│                                                             │
│   Full mode:                                                │
│   F01 context → exclusion → workers → merge → verify →      │
│   rank → frontier → validate → R03/R04 report → R01/R02 → │
│   optional P01/F06/F08 → ledger_finalize                    │
│                                                             │
│   Pipeline-only (--pipeline-only / JOBOPS_MODE=pipeline):   │
│   F01 context → P01 inbox → report → sheets/drive → finalize│
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Task types and agent skills

### Discovery / verify / rank / authorize

Unchanged from Phase 2–3: HTTP discovery only; V01–V04 verify; I01–I04 rank; authorize gate before any browser. Cap **1** / day. Never auto-retry after `SubmissionUncertain`.

### Pipeline (F07 P01)

| Cap | Behavior |
|---|---|
| P01 Inbox Outcome Interpreter | Classify Gmail-like messages → `OutcomeEvent`; reconcile `SubmissionUncertain` → Applied / Rejected |
| P02–P04 | Stub interfaces only (interview prep / follow-up / offer comparison) — no auto-send |

### Outreach (F06) — draft-only

| Cap | Behavior |
|---|---|
| O01–O04 | Verified contacts, referrals with consent, personalized drafts, follow-up planner |
| Hard rule | **No auto-send.** Approval required. Default stays drafts-only. |

### Learning (F08) — proposal-only

| Cap | Behavior |
|---|---|
| L01–L04 | Outcome / pattern / experiment / policy proposals |
| Hard rule | **Never** auto-writes `lib/policy.py` or eligibility thresholds |

### Reporting (F10)

| Cap | Behavior |
|---|---|
| R03 | Enrich `last-run-report.md`: eligible_count, verify stats, wall time, stubbed workers, cap remaining |
| R01 | Idempotent ledger→Sheets sync **plan** (offline when creds missing) |
| R02 | Ensure org/role Drive folder paths by `job_key` (local mirror) |
| R04 | Stuck locks / missing receipts / worker timeout heuristics → alerts JSON |

---

## 3. Orchestration and handoffs

### Pipeline stages (full)

```text
context → exclusion → workers → merge → verify → rank → frontier → validate
  → report_enrich → sheets_sync → drive_folders → (optional pipeline/outreach/learning)
  → ledger_finalize
```

### Pipeline-only

```text
context → inbox_outcomes → report_enrich → sheets_sync → drive_folders → ledger_finalize
```

```bash
./run --pipeline-only
# or
JOBOPS_MODE=pipeline PIPELINE_INBOX=path/to/inbox.json ./run
```

Agents talk **only through files** (and the ledger).

### Key artifacts

| Artifact | Producer | Consumer |
|---|---|---|
| `runs/<id>/run-context.json` | `run_context.py` | All stages |
| `handoff-state.json` | merger (+ verify/rank) | Frontier + validator |
| `runs/<id>/ranked-shortlist.json` | `rank_opportunities.py` | Frontier |
| `runs/<id>/pipeline-outcomes.json` | `inbox_outcomes.py` | Ledger / report |
| `runs/<id>/sheets-sync-plan.json` | `sheets_sync.py` | Human / live sync later |
| `runs/<id>/drive-folders.json` | `drive_artifacts.py` | Materials / drafts |
| `runs/<id>/run-metrics.json` | `run_report.py` | Report |
| `runs/<id>/reliability-alerts.json` | `run_report.py` | Ops |
| `runs/<id>/learning-batch.json` | `learning_proposals.py` | Approval queue |
| `runs/<id>/outreach-drafts.json` | `outreach_drafts.py` | Approval (no send) |
| `state/jobops.db` | `ledger.py` | Harness |
| `last-run-report.md` | Frontier + R03 enrich | Harness gate |

### Floor vs submit

| Knob | Default | Meaning |
|---|---|---|
| Discovery floor | **40** (`HANDOFF_FLOOR`) | Volume target |
| Submit / day | **1** | Hard cap |

---

## 4. Harness entry

```bash
./run
# HANDOFF_FLOOR=40 VERIFY_AGENT=0 SUBMIT_AGENT=0 ./run
# ./run --pipeline-only
# OUTREACH_DRAFTS=1 LEARNING_BATCH=1 ./run   # optional event slices
```

Requires local `agent` CLI (full mode) and Python 3 (`pip install -r requirements.txt`). Pipeline-only does not require `agent`.

### Lib scripts

| Script | Job |
|---|---|
| `lib/run_context.py` | F01 context lite |
| `lib/ledger.py` | SQLite WAL ledger |
| `lib/contracts.py` | Envelope + schema validation |
| `lib/policy.py` | Caps, tools, transitions, safety gates |
| `lib/verify_jobs.py` | F03 V01–V04 |
| `lib/rank_opportunities.py` | F04 I01–I04 |
| `lib/submission_authorize.py` | F05/F09 authorize gate |
| `lib/inbox_outcomes.py` | F07 P01 (+ P02–P04 stubs) |
| `lib/sheets_sync.py` | F10 R01 |
| `lib/drive_artifacts.py` | F10 R02 |
| `lib/run_report.py` | F10 R03/R04 |
| `lib/learning_proposals.py` | F08 L01–L04 |
| `lib/outreach_drafts.py` | F06 O01–O04 |
| `lib/merge_shards.py` | Shard → `handoff-state.json` |
| `lib/validate_handoff_state.py` | Accept / continue / reject |

---

## 5. Contracts, policy, evals

### Eval suites (Phase 1–4)

| Suite | Focus |
|---|---|
| E01–E06 + adversarial | Schema, dupes, availability, requirements, eligibility, provenance |
| E07 Materials | PDF identity; ATS/quality floors; fingerprint; no invented skills |
| E08 Submission safety | cap=1; lock; no Applied without receipt; uncertain ≠ Applied |
| E09 Outcome reconciliation | Uncertain + receipt → Applied; reject → Rejected; no double-count |
| E10 Learning safety | Proposal cannot mutate policy without approval |
| E11 Tracker sync | Ledger→Sheets idempotent; no duplicate rows on replay |
| E12 Drift / regression | Golden hard-miss traces; zero Eligible false-positive regression |

```bash
python3 -m pytest tests/ -q
```

---

## Quick file map

```text
cursor-job-automations/
├── run                      # orchestrator (Phase 4 stages + pipeline-only)
├── SYSTEM.md
├── harness-contract.md
├── contracts/               # JSON Schemas (incl. outcome / learning / outreach)
├── agents/
│   ├── discovery-worker.md
│   ├── verification.md
│   ├── frontier-rank-report.md
│   ├── frontier-submit.md
│   └── outreach-draft.md
├── lib/
│   ├── inbox_outcomes.py
│   ├── sheets_sync.py
│   ├── drive_artifacts.py
│   ├── learning_proposals.py
│   ├── outreach_drafts.py
│   ├── run_report.py
│   └── …
├── evals/fixtures/          # E01–E12 + adversarial + rank
└── tests/
```

## Explicit non-goals (still)

- 10 concurrent LLM frontiers
- Outreach auto-send
- Auto policy writes / adaptive source budgets
- Raising daily submit cap above 1
