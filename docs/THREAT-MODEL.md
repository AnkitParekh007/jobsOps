# jobsOps security threat model

**Status:** Living document for audit handoff. Not a certification. Automatic submission and outreach send remain off by default.

## Assets
- Candidate PII and verified facts in `JOBOPS_HOME` (outside the git checkout).
- Portal session cookies / browser profiles (never committed).
- Evidence HMAC signing key (`JOBOPS_EVIDENCE_SECRET` or `JOBOPS_HOME/secrets/evidence_hmac.key`).
- SQLite ledger (approvals, locks, submission reservations, artifacts, audit).
- Outbound network: job-board HTTP fetch; optional future browser submit / email send.

## Trust boundaries
1. **Untrusted:** job postings, email bodies, scraped HTML, agent prompts/outputs, provider CLIs.
2. **Trusted orchestrator:** `jobops` CLI, `lib/*` deterministic gates, ledger, `ToolBroker`, `AgentSandbox`, `ApprovalController`, `TrustedEvidenceIssuer` — only inside `OrchestratorContext`.
3. **Installation secrets:** evidence HMAC key — never embedded defaults, never inherited into agent child environments.

## Key threats and mitigations

| ID | Threat | Mitigation (implemented) | Residual risk |
|---|---|---|---|
| T1 | Prompt injection widens tool scope | `ToolBroker` seals allowlists; env/prompt hints informational; widen attempts raise | Third-party CLIs are not OS-sandboxed; spawn fails closed unless `JOBOPS_ALLOW_UNSANDBOXED_AGENT=1` |
| T2 | Agent forges submit consent | HMAC `trusted_evidence_v1` + durable `approvals` + `ApprovalController` | Key compromise = forge capability |
| T3 | Known/dev signing secret in production | Fail closed; reject known insecure values; no fallback secret | Operators must provision a key |
| T4 | SSRF / DNS rebinding via verify fetch | URL validation + connect-time IP pin + peer re-check on all `safe_http_fetch` paths | Exotic dual-stack / redirect races need continued tests |
| T5 | Fixture / mismatched PDF on live path | Recompute SHA-256; reject `fixture` method when live; validate `%PDF` magic; real multi-page fixture | Text extraction quality varies by PDF tooling |
| T6 | Duplicate / uncertain submit | Form locks, atomic daily reservations, mock ATS duplicate block, no auto-retry after `SubmissionUncertain` | Live portal adapters not production-certified |
| T7 | Accidental live submit | `JOBOPS_ALLOW_SUBMIT` / `JOBOPS_ENABLE_LIVE_SUBMIT` default `0` | Misconfiguration by operator |
| T8 | Evidence issuance from agent process | Issuer requires `OrchestratorContext` (not merely clearing `JOBOPS_AGENT_ROLE`) + approved ledger row | Logical isolation, not hardware TEE |
| T9 | Agent inherits signing/approval secrets | `build_agent_subprocess_env` explicit allowlist; secret keys stripped | Operator must not mount secrets into workspace readable by agents |
| T10 | Agent self-approves submissions | Approvals start `pending`; only authenticated `UserSession` via `ApprovalController` may approve | Session token theft |

## Out of scope (explicit)
- Full OS sandbox / seccomp for Cursor/Claude/Codex/Antigravity binaries (opt-in residual risk only).
- CAPTCHA / 2FA bypass.
- Guaranteeing third-party job-board ToS compliance for every source.

## Evidence for auditors
- Adversarial tests: `tests/test_security_adversarial_p0.py`, `tests/test_trust_boundary_remediation.py`, `tests/test_forge_authorization_negative.py`, `tests/test_url_safety.py`.
- Mock portal / ATS journey: `tests/test_mock_portal_e2e.py`, `lib/mock_ats_portal.py`.
- Runtime matrix: `docs/RUNTIME-CAPABILITIES.md`.
