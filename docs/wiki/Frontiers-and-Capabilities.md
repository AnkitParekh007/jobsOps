# Frontiers & Capabilities (F01–F10)

Frontiers are **logical capability groups**. Deterministic services implement the predictable work; agents are optional and gated.

| Frontier | Services (logical) | Output artifact |
|---|---|---|
| **F01** Context & State | Profile reader, preference resolver, history reconciler, session/lock inspector | `RunContext` |
| **F02** Discovery | Lane planner, ATS worker, employer career worker, coverage optimizer | `DiscoveredJob[]` |
| **F03** Verification | Availability, requirement extract, sponsorship/work model, duplicate/policy | `EligibilityDecision` |
| **F04** Intelligence | Profile fit, ATS match, opportunity signal, queue builder | `RankedOpportunity` |
| **F05** Application | Company research, materials, form prep, submission & receipt | `ApplicationPackage`, `SubmissionReceipt` |
| **F06** Outreach | Contact research, referral mapping, draft writer, follow-up planner | `OutreachDraft` |
| **F07** Pipeline | Inbox interpreter, interview prep, deadline monitor, offer comparator | `OutcomeEvent` |
| **F08** Learning | Cohort analysis, gap analysis, experiment designer, policy proposal | `LearningEvent` / `PolicyProposal` |
| **F09** Quality | Schema gate, truth/eligibility audit, materials/submission audit, drift | `EvalResult` |
| **F10** Operations | Tracker sync, artifact manager, run report, reliability monitor | `TrackerSync`, `RunReport` |

## Honesty about depth

- Roadmap phases (P0–P8) land capabilities incrementally — see [Roadmap & Readiness](Roadmap-and-Readiness.md).
- Sheets/Drive connectors currently emit **offline plans** (`live_api=false`); do not claim live Google API sync unless code and tests prove it.
- Outreach drafting may exist while **send** remains disabled.
- Live browser portal submission is **not** production-certified; mock portal coverage ≠ live ATS certification.

## Eligibility decisions

Every verification outcome is explicit: **Eligible**, **Needs review**, **Skipped**, **Closed**, or **Duplicate**, with evidence and reasons. Missing sponsorship or work-rights evidence must not collapse into Eligible.

Canonical table: [ARCHITECTURE.md](../ARCHITECTURE.md).
