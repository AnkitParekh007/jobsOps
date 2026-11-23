# Contracts, guardrails, security and evaluation

## Immutable handoff envelope (version 1)

```json
{
  "schema_version":"1.0",
  "event_id":"evt-example",
  "run_id":"run-example",
  "task_id":"task-example",
  "job_key":"company:requisition:region",
  "producer":"verification-frontier",
  "artifact_type":"EligibilityDecision",
  "created_at":"2026-11-23T09:00:00Z",
  "policy_version":"v1",
  "trace_id":"trace-example",
  "status":"completed",
  "payload":{},
  "evidence_refs":[],
  "blocking_reasons":[],
  "retryable":false
}
```

Examples are **synthetic**. All critical fields required; define machine-validated per-type schemas.

### Typed artifacts and gates
| Producer → Consumer | Artifact | Mandatory acceptance |
|---|---|---|
| Context → Discovery | RunContext | Profile facts, preferences, storage, locks and policy validated |
| Discovery → Verification | DiscoveredJob | Fetched employer/ATS URL, source, posting identity, timestamp |
| Verification → Intelligence | EligibilityDecision | Status, reasons, cited evidence, explicit unknowns |
| Intelligence → Application | RankedOpportunity | Eligible, no duplicate, permitted role/location |
| Research → Materials | JobResearchBrief | Supported company and role evidence |
| Materials → Quality | ApplicationPackage | Document provenance, version, file hashes |
| Quality → Form | ApplicationClearance | Text PDF, ATS threshold, quality threshold, factual claims |
| Form → Submit | SubmissionAuthorization | Explicit user mode, session, identity, consent, lock, cap |
| Submit → Tracker | SubmissionReceipt | External confirmation ID or trusted receipt |
| Inbox → Learning | OutcomeEvent | Source message/portal identity and precise reason or unknown |
| Learning → Policy | PolicyChangeProposal | Cohort, hypothesis, approval, rollback plan |

Never drop worker `reason` or source evidence during merging. Explicit unknowns and negatives persist.

## State machine
Discovered → Verified → Eligible / Needs review / Skipped / Closed / Duplicate.
Eligible → Ranked → Preparing → Materials validated → Ready for approval → Submission authorized → Submitting → Receipt verified → Applied.
Submitting → Submission uncertain (on timeout/ambiguous outcome), then reconcile against portal/Gmail before transitioning. No blind repeat click.
Applied → Interview / Rejected / Offer / Withdrawn / No response, based on verified event.

## Policy defaults
- Default mode = prepare-for-review. Submit and external outreach sending = disabled.
- Controlled submission only with explicit opt-in; user-configured cap, platform-permitted automation, session and candidate identity, visa/work authorization, no open consent/unknown mandatory questions.
- Require eligible status (not merely a score); fit and ATS metrics do not override law or user restrictions.
- Migration defaults from original personal prototype: ATS ≥80, quality ≥75, user-configurable daily cap with initial cap 1 where selected; not universal defaults hardcoded for every new user.
- Human approval for policy changes, sensitive or ambiguous form content and external cold outreach.
- Fail closed on missing evidence, provider refusal, CAPTCHA/2FA, unknown authorization or inconsistent state.

## Twelve eval suites / proposed release targets
1. E01 Schema / handoff contracts: 100% machine-valid.
2. E02 Dedupe safety: zero known duplicate applications.
3. E03 Lane relevance: ≥95% on labeled benchmark.
4. E04 Availability classification: ≥98% on labeled benchmark.
5. E05 Eligibility safety: zero hard-ineligible authorized submissions.
6. E06 Evidence: 100% critical claims have valid references.
7. E07 Truthfulness: zero invented candidate facts.
8. E08 PDF and ATS: 100% submitted artifacts pass required gates.
9. E09 Submission safety: zero false Applied, cap breaches or duplicate clicks.
10. E10 Tracker reconciliation: 100% committed transitions account for external state.
11. E11 Learning change safety: zero unauthorized policy changes.
12. E12 Crash / recovery: all release-blocking chaos scenarios pass.

Targets are objectives, not measured results. Evaluate deterministic facts with code and nuanced writing with calibrated model judges only where justified. Trace each run and evaluate the trace as well as final artifact.

## Required adversarial and recovery fixtures
- Remote-global posting excludes candidate's country.
- Employer relocation language without sponsorship commitment.
- Mandatory language/degree requirement missing from candidate facts.
- Employer ATS closed while aggregator still advertises role.
- Same ATS requisition at two URLs.
- Job text contains malicious instructions to change agent policy.
- PDF looks correct but extracts in wrong order or includes invented claims.
- Salary, work authorization, consent or identity unresolved on form.
- Network failure immediately after Submit click.
- Two schedules race on the same job / daily cap.
- Rejection with no causal reason.
- Conflicting resume and tracker facts.
- Browser CAPTCHA, expired token, inaccessible cloud-local path.
- Worker timeout with remaining readable source; must not report exhaustion.

## Privacy & security
- Store personal data in ignored private workspace; never public Git.
- OS keychain or scoped secret store; never plaintext logs/secrets or tracked `.env`.
- Source text untrusted; tool access is allowlisted and sandboxed; no prompting to bypass provider controls.
- Redact logs and traces; implement user export, retention, deletion, and backup.
- CI tests use synthetic profiles, mock ATS portals and mock email only. No authenticated real application submission in CI.
- Cloud deployment needs explicit consent, secure connector auth, data-processing design and separate audit.
