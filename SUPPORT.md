# Support

jobsOps is an open-source, experimental local-first harness. It is **not** a certified production service and provides no SLA.

## How to get help

| Topic | Channel |
|---|---|
| Usage questions, design discussion | [GitHub Discussions](https://github.com/AnkitParekh007/jobsOps/discussions) (when enabled) |
| Bugs and actionable defects | [GitHub Issues](https://github.com/AnkitParekh007/jobsOps/issues) |
| Security vulnerabilities | [SECURITY.md](SECURITY.md) — private reporting preferred |
| Contributing / PRs | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Deep product docs | [docs/wiki/Home.md](docs/wiki/Home.md) |

## Before opening an issue

1. Run `jobops doctor` and note the output (redact secrets).
2. Confirm you are not enabling live submit unintentionally (`JOBOPS_ALLOW_SUBMIT`, `JOBOPS_ENABLE_LIVE_SUBMIT`, `SUBMIT_AGENT` should stay `0` unless you knowingly opt in).
3. Search existing issues and Discussions.
4. Use synthetic fixtures — never paste real resumes, cookies, or tokens into public tickets.

## What maintainers will not do

- Guarantee interviews, offers, or universal ATS automation
- Bypass CAPTCHA, 2FA, rate limits, or consent
- Treat CI green as production certification
- Invent funding/sponsorship accounts — GitHub Sponsors / `FUNDING.yml` will be added only when a real maintainer sponsorship profile exists

## Status reminder

External application submission and outbound outreach sending remain **off by default**. See [docs/PRODUCTION-READINESS.md](docs/PRODUCTION-READINESS.md).
