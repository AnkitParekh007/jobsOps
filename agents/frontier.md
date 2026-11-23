# Frontier agent (compat redirect)

Phase 3 splits the frontier into two prompts:

| Prompt | When | Browser / submit |
|---|---|---|
| [`agents/frontier-rank-report.md`](frontier-rank-report.md) | **Default every run** (after verify + rank) | No |
| [`agents/frontier-submit.md`](frontier-submit.md) | Only if ranked shortlist non-empty **and** daily cap remaining | Yes, after `lib/submission_authorize.py` |

The harness (`./run`) invokes **rank-report** always. The submit agent is optional and gated by:

```bash
python3 lib/submission_authorize.py --check-only --shortlist runs/<id>/ranked-shortlist.json --run-id "$RUN_ID" --db state/jobops.db
```

If you are reading this file directly, follow **`frontier-rank-report.md`** unless the runtime prompt explicitly says submit mode.

Daily submit cap remains **1**. Never invent eligibility. Never auto-retry after `SubmissionUncertain`.
