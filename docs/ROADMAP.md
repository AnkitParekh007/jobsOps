# Delivery roadmap and gates

Work in independent increments. Never exchange completeness for a single enormous PR.

| Phase | Deliverable | Core acceptance |
|---|---|---|
| P0 | Install, CLI, init/doctor, secure workspace, SQLite, schemas, policy, tests | Fresh-install smoke; crash-safe state; deny unauthorized send; no secrets |
| P1 | Live ATS discovery, parallel HTTP scheduler, dedupe, source provenance | Real live-posting verification in opt-in smoke; synthetic reproducible fixtures; blocked ≠ exhausted |
| P2 | Eligibility, ranking, review queue | Labeled difficult sponsorship/work rights/remote fixtures pass; no ungrounded Eligible |
| P3 | Documents and application package | Verified fact provenance, PDF text extraction, ATS/quality gates; no unsupported claims |
| P4 | Approved safe form submission | Mock ATS E2E, exclusive lock, idempotency, consent, ambiguous click recovery, receipt |
| P5 | Email/Sheets/Drive, outreach and interviews | Reconciliation idempotence, distinct send permission and privacy controls |
| P6 | Claude/Codex/Cursor/Antigravity + MCP | Actual adapter smoke logs, graceful unsupported state, no core business duplication |
| P7 | Learning and evals | Approved policy proposals, cohort integrity, rollback and E01–E12 suites |
| P8 | Release readiness | Full clean-room install, accessibility/security review, CI, documentation, no critical defects |

## Phase exit checklist
- Traceability: tasks ↔ source ↔ code ↔ tests ↔ evidence.
- Functionality: negative and positive acceptance cases executed.
- Security: external calls are policy/permission-gated.
- Reliability: resumable errors, idempotent transitions and no duplicates.
- Observability: trace ID and report reference for all significant events.
- Portability: specific adapter claims tested on a real supported runtime.
- Docs: installation and troubleshooting match actual code.
- Owner accepts PR; subsequent phase begins from updated main.

## Release policy
**No production-go based solely on Cursor's self-evaluation.** Independent audit examines repository and tests after implementation. P0 issues block release; significant P1 issues require documented disposition. External auto-submission remains behind opt-in and platform-specific readiness gate.
