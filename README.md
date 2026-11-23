# cursor-job-automations

Fast local job-apply harness for Ankit Parekh’s Mac.

**System overview (agents, handoffs, harness, evals):** [SYSTEM.md](./SYSTEM.md)

```text
./run
  → F01 context + SQLite lock (state/jobops.db)
  → exclusion index
  → HTTP workers in parallel (fde-de, frontend-de, fde-ie)  target 15 each
  → ledger ingest + merge_shards.py → handoff-state.json   (default floor 40)
  → verify_jobs.py (V01–V04; optional VERIFY_AGENT=1)
  → rank_opportunities.py (I01–I04) → ranked-shortlist.json (top 5)
  → frontier-rank-report (always); optional frontier-submit if SUBMIT_AGENT=1 + authorize allows
  → validate + ledger finalize
```

Phase 1–3 unit evals: `python3 -m pytest tests/ -q` (requires `pip install -r requirements.txt`).

## Run

```bash
cd /Users/ankitparekh/Desktop/Projects/Automations/Job-Automations/cursor-job-automations
chmod +x run
./run
```

Env: `HANDOFF_FLOOR=40` (default) · `VERIFY_AGENT=0` · `SUBMIT_AGENT=0` (submit still gated by `lib/submission_authorize.py --check-only`).

Workers are **browser-forbidden** so they can run in parallel safely. Daily submit cap remains **1**.

## Key files

| Path | Role |
|---|---|
| `workers/manifest.json` | Workers, `parallel: true`, `target_matches: 15` |
| `agents/discovery-worker.md` | HTTP discovery sub-agent |
| `agents/verification.md` | Thin F03 agent (ambiguous sponsorship JSON only) |
| `agents/frontier-rank-report.md` | Default frontier (report) |
| `agents/frontier-submit.md` | Gated submit path |
| `agents/frontier.md` | Compat redirect |
| `lib/merge_shards.py` | Merge + floor |
| `lib/verify_jobs.py` | F03 verification after merge |
| `lib/rank_opportunities.py` | F04 ranking after verify |
| `lib/submission_authorize.py` | F09 authorize gate before browser |
| `runs/<run_id>/` | Shards + logs + ranked-shortlist |
