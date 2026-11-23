# Extensibility, user data, provider packaging and distribution contracts

**Specification — not a claim of shipped features.** This closes gaps identified from [reference study](REFERENCE-GAP-ANALYSIS.md).

## Installation and first run
- Target: a version-pinned, verified installer/entrypoint; interactive `jobops init`; `jobops doctor`; no secret credentials required for public discovery.
- Provide pip/pipx/uv installation supported by CI and an explicit supported Python version matrix. Do not advertise `curl | bash` as the only route.
- Onboarding reads resume/documents into private workspace, shows an evidence-backed candidate profile preview, records consent, and checks for missing/contradictory details.
- Model selection is optional, explicitly identifies local vs cloud providers, requires supported CLI/API authentication; never infer that chat subscription provides API token rights.
- Wizard should offer a small first win: evaluate one URL in research-only mode with source evidence before asking for full integrations.

## Immutable system/user data boundary
Suggested `JOBOPS_HOME` points to an OS-appropriate private data root outside checkout. Define defaults for macOS, Linux and Windows.
- **System layer** (updatable): code, schemas, default model instructions, vendor registry, deterministic parsers, synthetic test fixtures, reference docs.
- **User layer** (preserved): candidate profile and CV, facts, job history, applications, versions, approvals, decisions, contact preferences, provider secrets, cached descriptions, SQLite DB, logs with protected data, generated PDFs, backups.
- **Secrets layer**: keychain/credential manager with scoped tokens; never source-controlled or printed.
- App updates may migrate the user layer only with versioned, reversible migrations, pre-migration backup, verification and rollback plan; no `git pull` should erase data.
- Workspace must be exportable, encrypted-backup capable, recoverable and completely deletable on user request. Test restore in an isolated directory.
- Never claim an ephemeral remote agent session persists private files across restarts; it needs explicit durable encrypted storage.

## Plugin architecture (distinct from client plugins)
Plugin interface: `id`, `version`, `protocol_version`, `publisher`, `manifest_hash`, `license`, `capabilities`, `permissions`, `allowed_hosts`, `entrypoint`, `schema`, `config_schema`.
- Plugin capabilities: `source.search`, `source.fetch`, `source.health`, `ingest`, `notify.draft`, `export`, `tracker.sync`, `calendar.read`.
- **Forbidden:** plugin-owned unmediated `application.submit`, `outreach.send`, direct secrets access, policy writes, unscoped browser or shell.
- Installation phases: discover → inspect manifest → verify provenance/version/hash/signature if available → show permission diff → user approve → pin → health test → enable. Updated or off-registry plugin blocks until approved.
- Tool calls go through a capability broker; host allowlists, SSRF guards, path isolation, timeouts, quotas, logging and read/write scopes are enforced in code, not by a prompt.
- Vendor integrations can be in-tree vetted adapters. Community plugins remain untrusted code; consider process/container isolation before permitting them.
- Client packaging (Claude/Codex/Cursor/etc) is *not* the same as core integration plugins. Client wrappers only dispatch the same CLI/API command and should declare real tested compatibility.

## Provider source contract
A source is not merely a URL list. Model each source with `provider_id`, `source_type`, `official_or_aggregator`, `host_allowlist`, `auth_requirement`, `rate_policy`, `country_coverage`, `pagination_mode`, `job_id_strategy`, `freshness_ttl`, `liveness_probe`, `health_status`, `last_success_at`, `cursor`, `error_category`.
- Initial official ATS adapters: selected Greenhouse, Lever and Ashby public APIs only after current API terms/availability verified.
- Normalize roles/regions/salary/currency/seniority and store raw evidence + checksum.
- Never transform an aggregator page into employer evidence. Track provenance of aggregators separately.
- Differentiate accessible, blocked, degraded, truncated, exhausted and error. A failed worker is not exhaustion.
- Detect reposts and URL aliases by requisition identity plus canonicalized external ID, not just string equality.
- Revalidate liveness, sponsorship and work-mode claims immediately before allowed external action.

## Economics and quota safety
- Deterministic fast path for fetching, URL normalization, hard exclusions and simple triage.
- Explicit `economy`, `balanced`, `premium` reasoning tiers as *routing hints*, with provider capability checks.
- User-configured per-run and daily budgets for API spend, tokens, source requests, wall-clock time, portal actions and email drafts.
- On quota errors, checkpoint and resume; do not silently switch to a paid API or unsupported provider.
- Report real vs estimated costs; model-judge samples must justify incremental inference cost.

## Local dashboard target
Optional localhost-only accessible UI (not prerequisite for CLI):
- Onboarding completion, provider health and permissions.
- Discovery funnel: found / verified / eligible / prepared / applied / rejected / interview / offer.
- Detailed posting evidence and sponsorship unknowns.
- User approvals (submit/consent/outreach), failed-task retry and uncertain-submission reconciliation.
- Run timeline, costs, traces, provenance, source health and exports.
- Local bind `127.0.0.1` by default, CSRF protection and authenticated remote access only if explicitly deployed.

## Supported clients and truthful compatibility
- Shared `AGENTS.md`, root-locating `.agents/skills/jobops/SKILL.md` and optional thin wrappers per platform.
- Skill installed without engine: discover existing installation and explain setup; never improvise fake evaluation/report results.
- Test client invocation modes; do not state a slash command works solely because a file exists.
- ChatGPT needs a separately authorized authenticated hosted/connected service for remotely triggered local tasks; it cannot read a private Mac just because the user installed the repository.

## Required new eval cases
- Fresh install → profile setup → first verified posting with no model or external account.
- Update preserves all private profile/DB/artifact bytes; restore works after corruption simulation.
- Untrusted plugin attempts a disallowed host or secret read; capability broker denies and logs.
- Malformed plugin manifest, hash mismatch and version downgrade are rejected.
- Source returns an incomplete page or 403; worker cannot claim honest exhaustion.
- Cached JD injected instruction attempts a forbidden tool; source text remains data.
- Run exceeds token/spend budget; checkpoint with no unapproved provider switch.
- Local dashboard binds only loopback and protects mutation endpoints.
- Full remote session restart with state restored from explicit durable storage.
- External submit unknown after timeout never generates a second form submit.
