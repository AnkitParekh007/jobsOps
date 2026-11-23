# jobsOps security threat model

**Status:** Living document for audit handoff. Not a certification. Automatic submission and outreach send remain off by default. **Not production-ready.**

## Assets
- Candidate PII and verified facts in `JOBOPS_HOME` (outside the git checkout).
- Portal session cookies / browser profiles (never committed).
- Evidence HMAC signing key (`JOBOPS_EVIDENCE_SECRET` or `JOBOPS_HOME/secrets/evidence_hmac.key`).
- Control-plane authority key (`JOBOPS_HOME/secrets/orchestrator_authority.key`, mode 0600).
- SQLite ledger (approvals, user sessions, locks, submission reservations, artifacts, audit).
- Outbound network: job-board HTTP fetch; optional future browser submit / email send.

## Trust boundaries
1. **Untrusted:** job postings, email bodies, scraped HTML, agent prompts/outputs, provider CLIs.
2. **Trusted control plane:** `jobops` CLI with `JOBOPS_CONTROL_PLANE=1`, `ControlPlaneController`–issued `AuthorityGrant`, `OrchestratorContext`, ledger, `ToolBroker`, `AgentSandbox`, `ApprovalController` / `SessionIssuer`, `TrustedEvidenceIssuer`.
3. **Installation secrets:** evidence HMAC + authority keys — never embedded defaults, never inherited into agent child environments (`JOBOPS_HOME` / `PYTHONPATH` / `JOBOPS_CONTROL_PLANE` stripped).

## Key threats and mitigations

| ID | Threat | Mitigation (implemented) | Residual risk |
|---|---|---|---|
| T1 | Prompt injection widens tool scope | `ToolBroker` seals allowlists; env/prompt hints informational; widen attempts raise | Third-party CLIs are not OS-sandboxed; non-sensitive roles may opt in with `JOBOPS_ALLOW_UNSANDBOXED_AGENT=1` |
| T2 | Agent forges submit consent | HMAC `trusted_evidence_v1` + durable `approvals` + stored single-use `UserSession` via `SessionIssuer` | Key compromise = forge capability |
| T3 | Known/dev signing secret in production | Fail closed; reject known insecure values; no fallback secret | Operators must provision a key |
| T4 | SSRF / DNS rebinding via verify fetch | URL validation + connect-time IP pin + peer re-check on all `safe_http_fetch` paths | Exotic dual-stack / redirect races need continued tests |
| T5 | Fixture / mismatched PDF on live path | Recompute SHA-256; reject `fixture` method when live; validate `%PDF` magic; real multi-page fixture | Text extraction quality varies by PDF tooling |
| T6 | Duplicate / uncertain submit | Form locks, atomic daily reservations (required before authorize), consume/uncertain reservation lifecycle, no auto-retry after `SubmissionUncertain` | Live portal adapters not production-certified |
| T7 | Accidental live submit | `JOBOPS_ALLOW_SUBMIT` / `JOBOPS_ENABLE_LIVE_SUBMIT` default `0` | Misconfiguration by operator |
| T8 | Evidence issuance from agent process | Issuer requires verified `AuthorityGrant` inside `OrchestratorContext` (not merely clearing `JOBOPS_AGENT_ROLE`) + approved ledger row; control-plane flag never given to agents | Logical isolation, not hardware TEE; same-OS-user key theft remains residual |
| T9 | Agent inherits signing/approval secrets | `build_agent_subprocess_env` explicit allowlist; secret keys + `JOBOPS_HOME` / `PYTHONPATH` / `JOBOPS_CONTROL_PLANE` stripped | Operator must not mount secrets into agent-readable workspaces |
| T10 | Agent self-approves submissions | Approvals start `pending`; `SessionIssuer` binds stored single-use sessions to a principal + pending approval; explicit user action required; fabricated/expired/replayed sessions rejected | Session token theft within TTL before consume |
| T11 | Self-minted orchestrator privileges | `ControlPlaneController` issues signed grants; `OrchestratorContext` refuses self-created authority; agent contamination + missing control-plane flag block bootstrap | Process that already holds control-plane env + key can still issue grants |
| T12 | Unsandboxed AI on sensitive workflows | `frontier_submit` / `outreach` refuse `JOBOPS_ALLOW_UNSANDBOXED_AGENT=1` | Other roles may still opt into residual unsandboxed risk |

## Out of scope (explicit)
- Full OS sandbox / seccomp for Cursor/Claude/Codex/Antigravity binaries.
- CAPTCHA / 2FA bypass.
- Guaranteeing third-party job-board ToS compliance for every source.
- Multi-host distributed locking / HSM-backed keys.

## Evidence for auditors
- Adversarial tests: `tests/test_security_adversarial_p0.py`, `tests/test_trust_boundary_remediation.py`, `tests/test_authority_session_p0.py`, `tests/test_forge_authorization_negative.py`, `tests/test_url_safety.py`.
- Reservation / concurrency: `tests/test_reservation_concurrency_p1.py`.
- Mock portal / ATS journey: `tests/test_mock_portal_e2e.py`, `lib/mock_ats_portal.py`.
- Runtime matrix: `docs/RUNTIME-CAPABILITIES.md`.
