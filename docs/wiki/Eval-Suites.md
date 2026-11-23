# Eval Suites (E01–E12)

Targets below are **release objectives**, not measured production scores. Do not publish fabricated pass rates.

| ID | Suite | Release target (objective) |
|---|---|---|
| E01 | Schema / handoff contracts | 100% machine-valid |
| E02 | Dedupe safety | Zero known duplicate applications |
| E03 | Lane relevance | ≥95% on labeled benchmark |
| E04 | Availability classification | ≥98% on labeled benchmark |
| E05 | Eligibility safety | Zero hard-ineligible authorized submissions |
| E06 | Evidence | 100% critical claims have valid references |
| E07 | Truthfulness | Zero invented candidate facts |
| E08 | PDF and ATS | 100% submitted artifacts pass required gates |
| E09 | Submission safety | Zero false Applied, cap breaches, or duplicate clicks |
| E10 | Tracker reconciliation | 100% committed transitions account for external state |
| E11 | Learning change safety | Zero unauthorized policy changes |
| E12 | Crash / recovery | All release-blocking chaos scenarios pass |

## Required adversarial fixtures (sample)

- Relocation language without sponsorship commitment
- Aggregator still lists a closed employer ATS posting
- Same requisition at two URLs
- Malicious posting text attempting policy override
- Network failure immediately after Submit click
- Two schedules racing the same job / daily cap
- Worker timeout with remaining readable source (must not report exhaustion)

CI uses synthetic profiles and mock portals only. Evaluate deterministic facts with code; use calibrated model judges for nuanced writing only where justified, and always trace the run.

Details: [CONTRACTS-AND-EVALS.md](../CONTRACTS-AND-EVALS.md).
