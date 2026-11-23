# jobsOps wiki

Provider-neutral, policy-governed job search operations. A deterministic harness owns scheduling, policy, contracts, and the SQLite ledger. Optional AI adapters assist with ambiguous extraction, ranking explanations, and tailored writing — they do not own eligibility, submit authorization, or production claims.

## Status (read this first)

| Claim | Truth |
|---|---|
| Mergeable foundation | Yes — reviewed PRs + CI may land experimental substrate on `main` |
| Certified production release | **No** |
| Live application submit | **Off by default** |
| Outbound outreach send | **Off by default** |
| Fabricated experience / eligibility / receipts / eval scores | **Forbidden** |

Independent audit rubric: [PRODUCTION-READINESS.md](../PRODUCTION-READINESS.md). This wiki is documentation, not a certificate.

## What belongs where

| Need | Go to |
|---|---|
| Product boundaries and inventory | [PRODUCT-SCOPE.md](../PRODUCT-SCOPE.md) |
| DAG, frontiers, adapters | [Architecture](Architecture.md) · [ARCHITECTURE.md](../ARCHITECTURE.md) · [Motion visuals](../visuals/index.html) |
| Threats, SSRF, approvals | [Security & Threat Model](Security-and-Threat-Model.md) |
| F01–F10 capability map | [Frontiers & Capabilities](Frontiers-and-Capabilities.md) |
| Schemas and handoffs | [Contracts & Schemas](Contracts-and-Schemas.md) |
| E01–E12 targets | [Eval Suites](Eval-Suites.md) |
| Install and CLI | [CLI & Runtime](CLI-and-Runtime.md) |
| Runtime matrix | [Provider Adapters](Provider-Adapters.md) |
| Honest roadmap | [Roadmap & Readiness](Roadmap-and-Readiness.md) |
| Help / contribution | [FAQ](FAQ.md) · [Contributing](Contributing-and-Development.md) |

## Design principles

1. **Policy engine > prompt text.** External actions require durable grants, reservations, and gates — not natural-language permission.
2. **Untrusted inputs.** Postings, emails, resumes, and pages are data, never agent instructions.
3. **Fail closed.** Missing sponsorship evidence ⇒ Needs review. Worker timeout ≠ source exhaustion.
4. **No AI required for deterministic paths.** Users without a configured provider still run doctor, ledger, verify, and rank where implemented.
5. **Private data stays private.** Candidate facts live in `JOBOPS_HOME`, outside the git tree.

## Wiki hosting note

Canonical pages live in-repo under `docs/wiki/` (PR-reviewable). The GitHub Wiki feature may mirror or link here; avoid divergent long-form copies.
