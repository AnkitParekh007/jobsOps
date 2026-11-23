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
- Approvals start pending; only an interactive `InteractiveApprovalGate` confirmation (principal + job + fingerprint + challenge echo on the exact-type `TtyConfirmationChannel`) may mint an approval-bound single-use `UserSession`. Forgeable markers (e.g. `_jobops_trusted_interactive=True` on an arbitrary object) never qualify. Synthetic confirmation channels are confined to authenticated pytest configurations (`PYTEST_CURRENT_TEST` **and** `JOBOPS_ALLOW_TEST_CONFIRMATION=1`). Caller-controlled `explicit_user_action=True` is rejected. Trusted evidence and reservations require a `ControlPlaneController`-issued `AuthorityGrant` inside `OrchestratorContext` — `JOBOPS_CONTROL_PLANE=1` alone is insufficient without a **pre-existing** OS-gated `control_plane.privilege` credential (`jobops control-plane provision` only; **`jobops init` never installs credentials**); `jobops approve` does not install credentials, clear `JOBOPS_AGENT_ROLE`, or reset contamination. Test control-plane reset likewise requires pytest **and** `JOBOPS_ALLOW_TEST_CONTROL_PLANE_RESET=1`. Mode-restricted secrets limit other OS users; same-OS-user access remains a residual (documented) risk.
- Successful submission authorization requires a valid atomic reservation; Applied/Submitted consumes it and uncertain outcomes mark it non-retryable.
- Unsandboxed third-party AI execution remains disabled for sensitive workflows (`frontier_submit` / `outreach`).
- External auto-submit/outreach off by default; a plugin cannot create an alternate bypass route.
- Log redaction, injection tests, credentials rotation and dependency/vulnerability scanning are mandatory before release.
- The platform must preserve secure user data and provide deletion and export controls.
- See `docs/THREAT-MODEL.md` and `docs/RUNTIME-CAPABILITIES.md` for the living audit matrix.

## Support policy
A green CI / mergeable PR establishes a **mergeable foundation** only. It is **not** a certified production release. Until a tagged release is independently audited per `docs/PRODUCTION-READINESS.md`, the repository remains experimental and provides no guarantee of secure automation, job placement or continued service. Supported version ranges and disclosure timelines will be published when a first stable release is shipped.
