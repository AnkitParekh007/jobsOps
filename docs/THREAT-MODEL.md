# jobsOps security threat model

**Status:** Living document for audit handoff. Not a certification. Automatic submission and outreach send remain off by default.

## Assets
- Candidate PII and verified facts in `JOBOPS_HOME` (outside the git checkout).
- Portal session cookies / browser profiles (never committed).
- Evidence HMAC signing key (`JOBOPS_EVIDENCE_SECRET` or `JOBOPS_HOME/secrets/evidence_hmac.key`).
- SQLite ledger (approvals, locks, artifacts, audit).
- Outbound network: job-board HTTP fetch; optional future browser submit / email send.

## Trust boundaries
1. **Untrusted:** job postings, email bodies, scraped HTML, agent prompts/outputs, provider CLIs.
2. **Trusted orchestrator:** `jobops` CLI, `lib/*` deterministic gates, ledger, `ToolBroker`, `TrustedEvidenceIssuer`.
3. **Installation secrets:** evidence HMAC key — never embedded defaults, never passed to agent child env as a capability token.

## Key threats and mitigations

| ID | Threat | Mitigation (implemented) | Residual risk |
|---|---|---|---|
| T1 | Prompt injection widens tool scope | `ToolBroker` seals allowlists; env/prompt hints are informational; widen attempts raise | Third-party CLIs are not OS-sandboxed; see RUNTIME-CAPABILITIES |
| T2 | Agent forges submit consent | HMAC `trusted_evidence_v1` + durable `approvals` row bindings | Key compromise = forge capability |
| T3 | Known/dev signing secret in production | Fail closed; reject known insecure values; no fallback secret | Operators must provision a key |
| T4 | SSRF / DNS rebinding via verify fetch | URL validation + connect-time IP pin + peer re-check | Exotic dual-stack / redirect races need continued tests |
| T5 | Fixture / mismatched PDF on live path | Recompute SHA-256; reject `fixture` method when live; validate `%PDF` magic | Text extraction quality varies by PDF tooling |
| T6 | Duplicate / uncertain submit | Form locks, daily cap, no auto-retry after `SubmissionUncertain` | Live portal adapters not production-certified |
| T7 | Accidental live submit | `JOBOPS_ALLOW_SUBMIT` / `JOBOPS_ENABLE_LIVE_SUBMIT` default `0` | Misconfiguration by operator |
| T8 | Evidence issuance from agent process | Issuer refuses agent roles; requires ledger approval | Process isolation is logical, not hardware TEE |

## Out of scope (explicit)
- Full OS sandbox / seccomp for Cursor/Claude/Codex/Antigravity binaries.
- CAPTCHA / 2FA bypass.
- Guaranteeing third-party job-board ToS compliance for every source.

## Evidence for auditors
- Adversarial tests: `tests/test_security_adversarial_p0.py`, `tests/test_forge_authorization_negative.py`, `tests/test_url_safety.py`.
- Mock portal E2E: `tests/test_mock_portal_e2e.py` (no live ATS).
- Runtime matrix: `docs/RUNTIME-CAPABILITIES.md`.
