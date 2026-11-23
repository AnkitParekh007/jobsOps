# Frontier — submit (gated; cap 1)

You run **only** when the harness (or `lib/submission_authorize.py --check-only`) says the shortlist is non-empty **and** daily submit cap remaining &gt; 0.

## Preconditions (hard)

1. `ranked-shortlist.json` shortlist length ≥ 1.
2. Daily submit cap remaining = 1 (Asia/Calcutta day).
3. You will call / respect `lib/submission_authorize.py` before any browser submit.
4. Never auto-retry after `SubmissionUncertain`.

## Goals

1. Pick **at most one** role from the ranked shortlist (prefer rank 1).
2. Materials (LaTeX → PDF) under SOP §§9–13; ATS ≥ 80; quality ≥ 75; PDF fingerprint.
3. Run authorize gate → `ReadyForApproval` or `SubmissionAuthorized`.
4. Browser submit **only** if `SubmissionAuthorized`. Capture receipt evidence.
5. Update report + handoff; never mark Applied without receipt.

## Steps

### A. Pick ≤1 from shortlist

Read `runs/<run_id>/ranked-shortlist.json`. Prefer Eligible shortlist rank 1. Default to **zero** submits when materials/session gates are unclear — leave Ready for approval.

### B. Materials (A01–A03)

- Company brief + research handoff in Drive (thin; public sources only).
- Resume/cover from verified facts only — no invented Python / German fluency / credentials.
- Validate PDF text extract; record SHA-256 fingerprint (bytes preferred).
- Score second-pass ATS and quality against the **same** fingerprint.

### C. Authorize (deterministic — mandatory)

Build an application-package JSON and run:

```bash
python3 lib/submission_authorize.py \
  --package runs/<run_id>/application-package.input.json \
  --run-id "$RUN_ID" \
  --db state/jobops.db \
  --acquire-lock \
  --out runs/<run_id>/authorize-result.json
```

For dry-run / human confirmation:

```bash
python3 lib/submission_authorize.py --package ... --run-id "$RUN_ID" --dry-run --out ...
```

States: `Preparing` → `MaterialsValidated` → `ReadyForApproval` / `SubmissionAuthorized` → `Submitting` → `Applied` | `SubmissionUncertain`.

If state is `ReadyForApproval`, **stop** (do not browser-submit). Record evidence package.

If state is not `SubmissionAuthorized`, do not open the form.

### D. Submit (A04) — only if authorized

- Chrome only; account ankit77parekh@gmail.com.
- Hold form lock for this canonical URL.
- Never bypass CAPTCHA / OTP / legal acceptance.
- After click: record portal confirmation and Gmail receipt via:

```bash
python3 lib/submission_authorize.py \
  --record-outcome runs/<run_id>/submit-outcome.json \
  --run-id "$RUN_ID" \
  --db state/jobops.db
```

- `SubmissionUncertain` / On hold → **no retry** this run; Phase 4 reconcile later.
- Cap 1: any further passing role stays Ready for approval.

### E. Report update

Ensure `last-run-report.md` cites this `RUN_ID`, submit outcome or Ready for approval, and: no quota was promised, and no unverified submission was recorded.

## Forbidden

- Submitting without authorize `SubmissionAuthorized`
- Marking Applied without Gmail receipt (unless preferences explicitly allowlist the portal — default: no)
- Auto-retry after uncertain
- Raising daily cap above 1
