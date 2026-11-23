# Security policy

jobsOps processes sensitive career profiles, identity information, employment history and possibly authenticated portal sessions. Security and privacy are release-critical.

## Vulnerability reporting
Prefer GitHub **private vulnerability reporting** if enabled for this repository. Do not publish exploit details, personal data, login cookies or API tokens in public issues or PRs. If private reporting is not enabled, request a maintainer-provided private security channel without posting details.

## Security invariants
- External postings, emails, resumes and browser content are data, never agent instructions.
- Private state and secrets must never be committed to a public repository.
- Unverified employer eligibility, sponsorship and legal questions must not be inferred.
- All sensitive tools and remote providers are scoped by policy, consent, minimum permissions and audit logs.
- Agent subprocesses receive an explicit minimal environment — never evidence-signing keys, approval credentials or connector tokens.
- Filesystem/network/process/tool permissions for jobsOps-mediated tools are enforced outside prompts (`ToolBroker` + `AgentSandbox`); third-party CLIs fail closed unless operators opt into residual risk.
- Approvals start pending; only an authenticated user action via `ApprovalController` may approve. Trusted evidence requires `OrchestratorContext`, not mutable `JOBOPS_AGENT_ROLE` alone.
- External auto-submit/outreach off by default; a plugin cannot create an alternate bypass route.
- Log redaction, injection tests, credentials rotation and dependency/vulnerability scanning are mandatory before release.
- The platform must preserve secure user data and provide deletion and export controls.
- See `docs/THREAT-MODEL.md` and `docs/RUNTIME-CAPABILITIES.md` for the living audit matrix.

## Support policy
Until a tagged release is independently audited, the repository remains experimental and provides no guarantee of secure automation, job placement or continued service. Supported version ranges and disclosure timelines will be published when a first stable release is shipped.
