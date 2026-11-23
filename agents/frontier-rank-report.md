# Frontier — rank report (default every run)

You own **post-discovery reporting** only. Deterministic stages already ran: merge → verify → **rank** (`ranked-shortlist.json`).

## Goals (in order)

1. Finish a correct `last-run-report.md` for this `RUN_ID` — this is the success signal.
2. Consume the ranked shortlist; do **not** invent new Eligible rows.
3. Do **not** open a browser. Do **not** submit. Do **not** generate mass PDFs.

## Hard time budget

Aim to finish in under ~10 minutes. Prefer report-over-perfect-expand when gates are unclear.

## Steps

### A. Read state (fast)

- Read `handoff-state.json` (cumulative, floor_met, merge.shards, matches, `verification`, `ranking`).
- Read `runs/<run_id>/ranked-shortlist.json` — top-5 Eligible shortlist + Needs review human queue.
- Read `runs/<run_id>/run-context.json` and `verify-summary.json` if present.
- **Expand gate:** only if `floor_met` is false **and** `sources_remaining_readable` is non-empty **and** you have not already written `frontier-expand.json` this run: write **one** HTTP-only expand shard (`runs/<run_id>/shards/frontier-expand.json`) with at most **20** new matches from remaining readable sources, then **stop immediately** so the harness re-merges. No browser in expand. If floor already met or sources exhausted, skip expand entirely.

### B. Prep notes (no submit)

- Sessions proof on tracker if missing for this `RUN_ID` — one short note.
- Quick Gmail outcome skim for active applications only.
- Locks: confirm empty/open rules; **do not** open forms.

### C. Report from shortlist (mandatory)

Write `last-run-report.md` with:

- Run id, worker shard table (shard_id, matches, exhausted)
- Handoff cumulative vs floor; floor_met or exhausted
- Verify counts (Eligible / Needs review / Skipped / Closed / Duplicate) when present
- Ranked shortlist (≤5): org, role, country, priority / profile-fit / keyword-coverage / interview-opportunity — **no fictional % certainty**
- Human-review queue highlights (sponsorship blockers)
- Ready for approval / submitted (evidence URL) or none — usually none on this path
- Session blockers; Tracker + Drive ids
- Sentence: no quota was promised, and no unverified submission was recorded

Set `handoff-state.json` `phase` to `complete`. Keep `cumulative_handoff_matches == matches.length`.

## Local constraints

No Chrome on this path. Account / tracker / Drive ids remain as in SOP. Never invent eligibility. Daily submit cap remains **1** (submit path is a separate agent).
