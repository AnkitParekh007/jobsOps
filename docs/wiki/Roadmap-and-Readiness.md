# Roadmap & Production Readiness

## Honest status

| Layer | Status |
|---|---|
| Specs + contracts + policy-shaped foundation | Present and evolving on `main` |
| Mergeable experimental substrate | Possible when PRs pass review + CI |
| Certified production release | **Not claimed** |
| Live submit / outreach send | **Off by default**; not production-certified |

## Delivery phases (summary)

| Phase | Deliverable | Core acceptance idea |
|---|---|---|
| P0 | Install, CLI, init/doctor, workspace, SQLite, schemas, policy, tests | Fresh-install smoke; deny unauthorized send |
| P1 | Live ATS discovery, scheduler, dedupe, provenance | Blocked ≠ exhausted; real opt-in smoke separate from fixtures |
| P2 | Eligibility, ranking, review queue | No ungrounded Eligible |
| P3 | Documents / application package | Verified-fact provenance; no unsupported claims |
| P4 | Approved safe form submission | Mock ATS E2E, locks, idempotency, uncertain recovery |
| P5 | Email/Sheets/Drive, outreach, interviews | Distinct send permission; reconciliation |
| P6 | Multi-runtime adapters + MCP | Real smoke logs; graceful unsupported |
| P7 | Learning + E01–E12 | Approved proposals only; cohort integrity |
| P8 | Release readiness | Clean-room install, security review, explicit release decision |

Full gates: [ROADMAP.md](../ROADMAP.md).

## Production readiness protocol

1. Cursor / contributors implement in small PRs.
2. Owner reviews — no auto-merge of release claims.
3. Independent audit against [PRODUCTION-READINESS.md](../PRODUCTION-READINESS.md).
4. Remediation PRs; rerun gates.
5. Explicit release decision + tagged candidate.

**P0 blockers that always stop a release claim:** false professional/work-auth claims, unauthorized external submit/outreach, duplicate submit after race/timeout, Applied without authentic receipt, leaked credentials/PII, prompt injection overriding tool policy, missing browser identity/consent guards, false adapter/scheduler claims.

## What this page deliberately does not say

- That any phase is “done” without test evidence in-repo.
- That CI green equals production-ready.
- That live Google Sheets/Drive, live portal submit, or outreach send are certified.
