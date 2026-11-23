# Reference study: career-ops vs jobsOps

**Reference:** https://github.com/career-ops-hq/career-ops (default branch, reviewed 2026-11-23). **Our baseline:** https://github.com/AnkitParekh007/jobsOps (main). This document records source-grounded observations and proposed jobsOps additions, not an assertion that jobsOps already implements them.

## Principles
- Learn from architecture and user experience. **Do not copy code, documentation, images, logos, trademarks, analytics, or claims** without explicit review of per-file license, attribution, assets, and dependencies.
- Do not collapse jobsOps into a clone. jobsOps targets a **provider-independent, policy-governed multi-frontier runtime** with durable state, optional controlled submissions, evidence, and independent evals.
- The reference project's own apply guidance states **it prepares forms but does not click Submit**. jobsOps auto-submission is a distinct, opt-in capability with stronger authorization and receipt gates; do not claim the reference supports it.
- Docs/features in the reference are source-grounded; implementation details require tests, independent security audit, and owner approval.

## Evidence and differences

| Theme | Evidence in reference | jobsOps baseline | Proposed gap closure | Priority |
|---|---|---|---|---|
| One-command install/onboarding | `docs/SETUP.md`: npx installer, chat-driven first run | Target CLI described, no implementation | Tagged pipx/uv/pip release, CLI setup wizard, migration and clean-install acceptance | P0 |
| Universal skill router | `.agents/skills/career-ops/SKILL.md`: mode routing and install/root resolution | AGENTS.md/CLAUDE.md only | `.agents/skills/jobops/SKILL.md` delegating to actual CLI; truthful unsupported handling | P0 |
| Multi-client packaging | `docs/SUPPORTED_CLIS.md`, `.claude-plugin`, `.codex-plugin`, `.cursor-plugin`, `.antigravitycli`, wrappers | Platform instructions only | Testable client-specific wrappers/metadata; compatibility matrix and smoke logs | P2 |
| System vs private user layers | `DATA_CONTRACT.md`: preservation on update and independent data root | .gitignore and generic SQLite mention | Strict filesystem ownership, XDG/OS data root, update/rollback/backup and migration contract | P0 |
| Plugin registry and trust | `docs/PLUGINS.md`: manifests, pinned versions, host allowlists, user enablement, tamper checks | Adapters only as architecture | Signed/versioned plugin spec, capability scopes, allowlisted hosts, SSRF protection, offline-safe default, trust verification | P2 |
| Mature source ecosystem | `docs/SUPPORTED_JOB_BOARDS.md` and `providers/`: documented vendor adapters | High-level ATS source requirements | Source manifest, explicit provider capabilities, pagination, partial coverage, freshness, health and compliance tests | P1 |
| Posting integrity | `docs/POSTING_GUARD.md`: hidden text / injected commands / Unicode anomalies detection | Prompt injection policy stated | Deterministic integrity scanner and separate trusted-document parser with forensic evidence and adversarial fixtures | P1 |
| Liveness and re-posts | `docs/KEEPING_PORTALS_LIVE.md`, `check-liveness.mjs`, `detect-reposts.mjs` | Generic liveness/identity | Before-apply revalidation, archive fingerprints, repost lineage and identity matching | P1 |
| Cheap deterministic discovery | `docs/AUTOMATION.md`: no-model scanning/triage, separate scheduled sweeps | Planned HTTP workers | Token-free fast path; only invoke LLM for uncertain, high-value shortlists | P1 |
| Cost tiers and budget | `docs/RUNNING_ON_A_BUDGET.md`: economy/standard/premium, quotas and provider billing | Conceptual budgets | Per-run/daily quotas, routing tiers, estimated vs actual spend, grace/stop, privacy-informed provider choice | P1 |
| Local dashboard | `docs/WEB_UI.md`: localhost UI and service lifecycle | Text reporting spec | Optional localhost job funnel, approval inbox, evidence drawer, run timeline and accessibility | P3 |
| Browser form assist | `docs/APPLY_AUTOFILL.md`: ATS-specific safe fill and knockout pre-scan; manual Submit | Broad browser adapter specification | Adapter capability matrix, preflight knockout questions, user handoff, explicit uncertainty after click | P3 |
| Backups and recovery | `docs/BACKUP_STRATEGIES.md`: personal data root and backup recipes | SQLite durability but no user UX | Encrypted export, backup verify, disaster restore, cross-version migrations, OS sleep behavior | P1 |
| Privacy boundary | `docs/PRIVACY.md`: optional outbound PII guard with documented limits | Generic redaction/secrets policy | Explicit model-payload preview, protect/allow rules, outbound policy, consent + test probes | P0 |
| Maintainership and open-source UX | `CONTRIBUTING.md`, `SECURITY.md`, `.github/ISSUE_TEMPLATE`, workflows | LICENSE + spec docs only | Contributor guide, support & disclosure policy, CI, CODEOWNERS and templates | P0–P2 |
| CI/evaluation infrastructure | `evals/`, `.github/workflows/test.yml`, code scanning, SBOM workflows | Proposed 12 evals | Golden fixtures, coverage, supply-chain baseline and cross-platform release gates | P0–P2 |
| Local vs remote isolation | `docs/SETUP.md` caveats for web sessions with ephemeral VMs | Conceptual limitation noted | Durable remote workspace contract + explicit migration/export strategy; no claim cloud sees local user data | P2 |
| Documentation and community discoverability | Localized README variants, media, governance and onboarding examples | Basic README | Accessible screenshots after implementation; searchable FAQ/troubleshooting; translations only after English stabilizes | P3 |

## What to adopt first — in descending order
1. **P0 ownership/data contract, install UX, security/privacy and testable agent router**. Prevent personal data loss and dangerous install flows.
2. **P1 source registry, deterministic triage, posting integrity, liveness, financial limits, backup/restore**. This directly improves both eligible-job yield and reliability.
3. **P2 plugin trust, client packaging, CI security and reproducible compatibility**. Makes it distributable beyond Cursor without false marketing claims.
4. **P3 dashboard + safe form assistance + user-facing feedback**, after core and policies work.
5. **P4 community/translation and marketplace packaging**, after public beta quality gates.

## Source index (links to originals, not mirrored copies)
- [Setup](https://github.com/career-ops-hq/career-ops/blob/main/docs/SETUP.md)
- [Supported CLIs](https://github.com/career-ops-hq/career-ops/blob/main/docs/SUPPORTED_CLIS.md)
- [Shared skill router](https://github.com/career-ops-hq/career-ops/blob/main/.agents/skills/career-ops/SKILL.md)
- [User/system data contract](https://github.com/career-ops-hq/career-ops/blob/main/DATA_CONTRACT.md)
- [Plugins and trust](https://github.com/career-ops-hq/career-ops/blob/main/docs/PLUGINS.md)
- [Job boards](https://github.com/career-ops-hq/career-ops/blob/main/docs/SUPPORTED_JOB_BOARDS.md)
- [Automation](https://github.com/career-ops-hq/career-ops/blob/main/docs/AUTOMATION.md)
- [Integrity gate](https://github.com/career-ops-hq/career-ops/blob/main/docs/POSTING_GUARD.md)
- [Running on a budget](https://github.com/career-ops-hq/career-ops/blob/main/docs/RUNNING_ON_A_BUDGET.md)
- [Local web UI](https://github.com/career-ops-hq/career-ops/blob/main/docs/WEB_UI.md)
- [Form assistance](https://github.com/career-ops-hq/career-ops/blob/main/docs/APPLY_AUTOFILL.md)
- [Backup](https://github.com/career-ops-hq/career-ops/blob/main/docs/BACKUP_STRATEGIES.md)
- [Privacy](https://github.com/career-ops-hq/career-ops/blob/main/docs/PRIVACY.md)
- [Contributing](https://github.com/career-ops-hq/career-ops/blob/main/CONTRIBUTING.md)

## Deliberate exclusions
- Do not import thousands of providers or large seed lists without source-specific validation and license/compliance review.
- Do not copy social proof, badges, press logos, product branding, stats, endorsements or screenshots.
- Do not infer subscription billing, CLI trust mechanisms, or API availability are identical between products or versions.
- Do not expose automatic submission as a plugin hook or allow an extension to override the policy engine.
