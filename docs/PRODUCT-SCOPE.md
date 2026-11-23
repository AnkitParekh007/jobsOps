# Product scope and task inventory

## Product goal
Help a user improve **qualified interview and offer outcomes** while keeping all decisions traceable, consentful and safe. Discovery counts and application volume are leading indicators, not the success metric.

## Personas and modes
- New job seeker: guided onboarding, resume import, preferences, local-only tracker.
- Technical user: CLI, local scheduler, provider adapters, MCP.
- Power user: approved connected services, controls, auditable automation.
- Modes: **research-only**, **prepare-for-review** (default), **controlled-auto-submit** (explicit opt-in, separate policy gate). Outreach sending is separately permissioned.
- Independent scheduled, event-driven and user-triggered runs; no requirement for an IDE window.

## Canonical work inventory

### 1. Candidate context
- Verified facts, skills with supporting evidence, work history, contact and availability.
- Job targets: role families, seniority, industry, country/city, remote/hybrid, relocation.
- Work authorization / visa sponsorship, compensation constraints, languages, travel requirements.
- Resume versions, approvals, disallowed claims and policy history.
- Read-only review of conflicts; no guessing or automatic profile rewriting.

### 2. Discovery
- Employer-operated careers and supported public ATS APIs; HTTP-first.
- Search by role × region × employer/source; distribute with concurrency and rate budgets.
- Freshness, posting identity, pagination, source rotation, changed-posting detection.
- URL canonicalization, employer/requisition-level dedupe, company blacklists.
- Search coverage and source health; blocked pages marked blocked, not exhausted.

### 3. Verification and eligibility
- Open employer/ATS posting body, application state, job location and requirements.
- Required vs preferred skills, language, legal work rights, sponsorship, remote location constraints, mandatory travel, salary when available.
- Explicit decisions: Eligible, Needs review, Skipped, Closed, Duplicate; every decision has evidence and reasons.
- Recheck live status before application actions, never assume sponsorship from relocation openness.

### 4. Intelligence and ranking
- Separate profile fit, ATS document match, opportunity evidence, freshness, and uncertainty.
- Prioritize eligible roles by user preferences and realistic fit; no invented probability.
- Produce Tier 1/2/3 and actionable shortlist; avoid optimizing solely for quota.

### 5. Application materials and forms
- Company/team/role research brief with citations.
- Verified-fact resume tailoring, readable single-column text-based PDF, concise cover letter.
- Truthful screening answers; surface unknown legal/salary/consent answers to the user.
- ATS ≥80 and material quality ≥75 are **initial migration policy defaults** from the prototype, configurable only through explicit policy version/approval. Scores never override hard eligibility.
- Form filling, document uploads, identity check, real session check, approval, daily cap, submission lock, receipt verification.
- Ambiguous submission becomes Submission uncertain; no blind retry.

### 6. Outreach, networking and referrals
- Verified public professional contacts and real connections; no scraping of protected areas.
- Personalized drafts and referral requests; opt-out, contact frequency, deliverability.
- Sending requires approval and separate permission; recorded communication history.

### 7. Inbox, interview and offers
- Incremental email reconciliation: receipts, interview requests, assessments, rejections, offers.
- Calendar requests and deadlines, interview/company briefs, study plan and follow-up drafts.
- Preserve stated rejection reason separately from inferred hypotheses.

### 8. Self-improvement
- Immutable OutcomeEvents and matured cohort analytics.
- Source performance, role/region eligibility yield and resume emphasis experiments.
- Minimum 20 matured comparable applications per lane/country before claiming an improved resume emphasis (migrated rule); express uncertainty.
- Approval for proposed learning-policy changes, versioning, rollback and regression checks.

### 9. Tracking, operations and reporting
- SQLite event ledger and transactional outbox; external tracker/email/Drive are synchronized views/connectors.
- Durable task queue, idempotency, leases, checkpoints, retries, dead-letter queue, budgets, alerts.
- Runs, evidence references, costs, timings, errors, review queue and daily dashboard.
- Private workspace and exports; retention/deletion controls and redacted logs.

## Success metrics
- Primary: qualified interviews per matured eligible-application cohort; offers, time-to-interview.
- Discovery: distinct verified postings, eligibility yield, freshness, source error rates.
- Workflow: successful verified receipts / authorized attempts, time per eligible job, cost per eligible job.
- Reliability: duplicate submissions=0, unsupported claims=0, policy bypasses=0; stale states and reconciliation errors.
- Report denominators, confidence intervals when useful, dates and evidence; never invent outcome statistics.

## Scope boundaries
No guarantee of interviews, offers, unrestricted portal automation, universal sponsorship detection, or always-on execution on a sleeping laptop. A connected chat product is not synonymous with a headless local runtime.
