# FAQ

### Is jobsOps production-ready?

**No.** The repository may contain a mergeable experimental foundation with CI. A certified production release requires an independent audit per [PRODUCTION-READINESS.md](../PRODUCTION-READINESS.md) and an explicit release decision.

### Does a green CI mean I can enable live submit?

**No.** CI forces submit and outreach send off. Live submit still needs explicit env flags, authorize checks, reservations, and approval — and remains uncertified for production.

### Is this a Claude-only project?

**No.** jobsOps is provider-neutral. Adapters exist for Cursor, Claude Code, Codex, Antigravity, and a deterministic runtime that needs no model.

### Where is my candidate data stored?

Under `JOBOPS_HOME` (OS Application Support / XDG), outside the git checkout. Do not commit private profiles into the public repo.

### Why did eligibility become "Needs review"?

Missing or ambiguous sponsorship, work rights, location, or other hard evidence. The system must not invent Eligible.

### Worker timed out — is the source exhausted?

**No.** Timeouts and failures are not honest source exhaustion. Fabricated or inaccessible jobs must not count toward a discovery floor.

### Can plugins or agents bypass the policy engine?

They must not. Source adapters cannot skip eligibility or consent. Approvals and control-plane grants are ledger-backed, not prompt-backed.

### How do I report a vulnerability?

Use GitHub private vulnerability reporting when enabled. See [SECURITY.md](../../SECURITY.md). Never post tokens, cookies, or exploit detail in public issues.

### Is sponsorship / funding configured?

Not via invented Patreon/OpenCollective links. If GitHub Sponsors for the maintainer becomes available, it will be declared in `.github/FUNDING.yml`. Until then, use Discussions or issues for collaboration — not fake funding badges.
