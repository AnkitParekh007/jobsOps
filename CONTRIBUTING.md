# Contributing to jobsOps

Thank you for improving jobsOps. This project is an open-source, local-first career automation harness. We welcome focused bug fixes, source adapters, documentation, accessibility improvements, tests and user experience contributions.

## Before you start
- Read [AGENTS.md](AGENTS.md), the [wiki Home](docs/wiki/Home.md), [architecture](docs/ARCHITECTURE.md), [contracts and evals](docs/CONTRACTS-AND-EVALS.md) and [reference gaps](docs/REFERENCE-GAP-ANALYSIS.md).
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md). For usage questions prefer [Discussions](https://github.com/AnkitParekh007/jobsOps/discussions) or [SUPPORT.md](SUPPORT.md).
- New capabilities and high-risk changes (submission, secrets, plugin permissions, legal/authorization logic) should start with an issue and a threat/acceptance checklist. Small bug fixes and docs can be proposed directly.
- Use synthetic profiles and mock ATS/emails. **Never commit real resumes, job search history, access tokens, cookies or another person's private details.**
- Document the provider API/terms, pagination, liveness and rate limits for any new job source.
- Don't represent screenshot-only or placeholder logic as working production integration.

## Pull request expectations
1. State the user problem, scope and linked issue.
2. Explain changes to contracts, permissions, migrations and provider support.
3. Include deterministic unit tests and adversarial/negative tests.
4. Describe commands actually executed, CI result and benchmark evidence.
5. List residual risks and whether external actions are disabled.
6. For documentation, verify commands and hyperlinks where possible.
7. Do not self-merge a production feature; maintainer review and independent release audit apply.

## Plugin and source contributions
Use the manifest/host-capability model in [Extensibility](docs/EXTENSIBILITY-AND-DISTRIBUTION.md). A new third-party provider is not entitled to submit applications or read user secrets. Source adapters cannot bypass eligibility checks or consent.

## Licensing and attribution
Check upstream and dependency licenses before adapting third-party work. Attribute borrowed code correctly and do not copy another project's trademarks, promotional graphics, user stories or README copy. Feature ideas and general architecture patterns are not an invitation to copy protected expression.

## Reporting security problems
Do **not** publish exploitable vulnerability details or credentials in a public issue. Contact maintainers privately through GitHub's private vulnerability reporting feature when enabled, or the repository's published security contact. If no private channel is available, request one without disclosing sensitive details.

## Project status
Product specification and incremental implementation may be incomplete. Check README for current supported commands and verify actual tests before claims of functionality.
