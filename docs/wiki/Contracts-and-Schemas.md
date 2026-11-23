# Contracts & Schemas

Machine-validated handoffs keep frontiers honest. Natural-language agent output is never the sole authority for state transitions.

## Immutable handoff envelope (v1)

Critical fields: `schema_version`, `event_id`, `run_id`, `task_id`, `job_key`, `producer`, `artifact_type`, `created_at`, `policy_version`, `trace_id`, `status`, `payload`, `evidence_refs`, `blocking_reasons`, `retryable`.

Examples in docs are **synthetic**. Schemas live in [`contracts/`](../../contracts/):

| Schema file | Artifact |
|---|---|
| `envelope.schema.json` | Common envelope |
| `run-context.schema.json` | F01 context |
| `discovered-job.schema.json` | F02 discovery |
| `eligibility-decision.schema.json` | F03 verification |
| `ranked-opportunity.schema.json` | F04 ranking |
| `application-package.schema.json` | F05 materials |
| `submission-receipt.schema.json` | F05 receipt |
| `outreach-draft.schema.json` | F06 drafts |
| `outcome-event.schema.json` | F07 outcomes |
| `learning-event.schema.json` / `experiment-proposal.schema.json` | F08 |
| `handoff-state.schema.json` | Merged harness state |

## Producer → consumer gates

| Path | Artifact | Must prove |
|---|---|---|
| Context → Discovery | `RunContext` | Profile, preferences, storage, locks, policy |
| Discovery → Verification | `DiscoveredJob` | Employer/ATS URL, source, identity, timestamp |
| Verification → Intelligence | `EligibilityDecision` | Status, reasons, evidence, explicit unknowns |
| Intelligence → Application | `RankedOpportunity` | Eligible, not duplicate, permitted role/location |
| Quality → Form | Clearance | Text PDF, ATS/quality thresholds, factual claims |
| Form → Submit | `SubmissionAuthorization` | Mode, session, identity, consent, lock, cap |
| Submit → Tracker | `SubmissionReceipt` | External confirmation or trusted receipt |

Never drop worker `reason` or source evidence during merges. Explicit unknowns persist.

## State machine (summary)

```text
Discovered → Verified → Eligible | Needs review | Skipped | Closed | Duplicate
Eligible → Ranked → Preparing → Materials validated → Ready for approval
  → Submission authorized → Submitting → Receipt verified → Applied
Submitting → Submission uncertain (timeout/ambiguous) → reconcile before retry
```

**Clicked submit ≠ Applied.** Ambiguous outcomes stay uncertain until reconciled.

Full text: [CONTRACTS-AND-EVALS.md](../CONTRACTS-AND-EVALS.md).
