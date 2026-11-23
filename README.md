# jobsOps

**Provider-neutral, local-first agentic career automation platform.**

> **Status: architecture and implementation specification. Not production-ready.** This repository currently documents the target system. Do not describe discovery, auto-apply, connector support, scheduling, or autonomous execution as implemented until code and evidence demonstrate them.

jobsOps coordinates job discovery, live-posting verification, candidate-fit ranking, tailored application preparation, controlled submission, outreach drafts, interview tracking, feedback analysis, and reporting. A deterministic harness owns workflow state and permissions; AI agents perform bounded tasks. Users can choose Claude Code, OpenAI Codex, Cursor, Google Antigravity, an API model, or deterministic-only operation through adapters—not separate forks of the product.

## Start here

- [Career-ops reference study and missing features](docs/REFERENCE-GAP-ANALYSIS.md)
- [Extensibility, installation and distribution contracts](docs/EXTENSIBILITY-AND-DISTRIBUTION.md)
- [Contributing](CONTRIBUTING.md) and [security](SECURITY.md)
- [Product and complete task inventory](docs/PRODUCT-SCOPE.md)
- [Architecture, agents, subagents and handoffs](docs/ARCHITECTURE.md)
- [Installation and user journey across AI platforms](docs/USER-GUIDE.md)
- [Contracts, policies, security and evals](docs/CONTRACTS-AND-EVALS.md)
- [Cursor implementation master brief](docs/CURSOR-IMPLEMENTATION.md)
- [Phased delivery and acceptance criteria](docs/ROADMAP.md)
- [Production-readiness audit gate](docs/PRODUCTION-READINESS.md)
- [Repository-wide instructions](AGENTS.md)

## Intended user experience (commands below are targets, NOT currently implemented)

```bash
git clone https://github.com/AnkitParekh007/jobsOps.git
cd jobsOps
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -e .
jobops init
jobops doctor
jobops run --workflow discovery --dry-run
jobops run --workflow daily-search
jobops report
jobops schedule enable daily-job-search
```

The implementation must initially offer **research-only** and **prepare-for-review** modes; external application submission and outreach sending remain disabled by default. Controlled auto-submission is a separate opt-in capability requiring supported authorization, eligibility, identity, duplicate, quota, consent, and receipt gates. Browser CAPTCHA/2FA are never bypassed.

## How the parts fit

```text
CLI / Claude Code / Codex / Cursor / Antigravity / MCP / authenticated API
                         |
                   jobsOps CLI/API
                         |
        Policy gate + durable workflow orchestrator
                         |
    Context -> Discovery -> Verification -> Ranking
                         |
            Preparation -> Independent evals
                         |
           Authorization -> Submit / Hold
                         |
          Receipts -> Tracker -> Learning
                         |
              SQLite event ledger
```

## Distribution principles

1. One core engine and common typed handoff schema.
2. `AGENTS.md` is universal; product-specific agent wrappers only delegate.
3. SQLite and local private workspace are canonical; Sheets, Drive, email and remote services are optional adapters.
4. Provider/agent capabilities must be detected at runtime; chat-only products do not automatically have local file, browser, or background-run access.
5. No personal resume, secrets, tokens, addresses, proprietary old-run artifacts or authenticated browser sessions in the public repo.
6. Status `Applied` requires authoritative evidence; ambiguous submit attempts are reconciled, never blindly retried.

## Development workflow

Cursor should implement in small reviewable PRs following [the implementation brief](docs/CURSOR-IMPLEMENTATION.md), with tests, traces and documentation updated for each phase. No merge-to-main or production declaration before independent audit.

## License

See [LICENSE](LICENSE).
