# Production readiness and independent audit protocol

**Planned milestone:** after Cursor finishes implementation and PRs are reviewed/merged, an independent audit will examine the actual repository. This document is the audit rubric, not a certification.

## Audit dimensions
1. **Product:** onboarding, permissions, easy first run, clear no-AI capability and errors.
2. **Architecture:** modular runtime, deterministic orchestrator, 10 logical frontiers, typed handoffs, least privilege.
3. **Portability:** Claude Code, Codex, Cursor, Antigravity tested adapters; unsupported modes gracefully rejected; ChatGPT service integration only if implemented/authenticated.
4. **Discovery:** source compliance, live evidence, dedupe by requisition, blocked source reporting, source freshness.
5. **Eligibility:** accurate mandatory vs preferred, sponsorship, country work rights, no inferred approval.
6. **Documents:** verified facts, compliant text extraction, ATS/quality eval, privacy of generated files.
7. **Submission:** browser identity/session, strict cap/locks, consent, safe abort, receipt, post-click uncertainty.
8. **Outreach and email:** verified contacts, user permission, opt-out, no accidental duplicate send.
9. **State:** SQLite durability, migrations, outbox, replay/restart, backup/export/delete, reconciliation.
10. **Evals:** E01–E12 reproducible and documented, adversarial and failure injections.
11. **Security/privacy:** secrets, dependency audit, redaction, prompt injection, account isolation, threat model.
12. **Operations:** bounded time/cost/concurrency, retry policy, monitoring, run reporting, install/update/uninstall.

## P0 release blockers
- Any unsupported professional claim / false work authorization claim in submitted material.
- Any unauthorized external application or outreach submission.
- Any duplicate submission after timeout or concurrency race.
- Status Applied without authentic supporting receipt.
- Credentials or candidate personal data leaked into repository/logs.
- Prompt injection can override tool permissions or policy.
- Critical missing guard on browser session/identity/consent.
- False claims that unimplemented provider adapters or scheduled execution work.

## Required evidence to hand to auditor
- Commit SHA, release candidate tag, PR/CI status, dependency SBOM.
- OS × platform compatibility matrix with actual CLI sessions.
- Clean install logs and documented commands.
- Pytest + integration + E01–E12 eval output, test fixtures and coverage.
- Controlled mock-portal E2E traces for successful, blocked, uncertain and duplicate attempts.
- Source compliance notes and API throttling logs.
- Security/privacy threat model and findings.
- Performance measurements: time/cost per verified eligible posting and resource use.
- Open risk register (P0/P1/P2), owner and mitigation.

## Post-implementation workflow
Cursor implements → owner reviews PRs → independent audit → remediation PRs → rerun all gates → explicit release decision → tagged candidate release. Never auto-merge, certify or publish on the basis of a document alone.
