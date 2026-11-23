# Review-first release candidate — evidence and hold points

This change provides a **usable, local, read-only public ATS research-to-review
workflow**. It does **not** implement or certify unattended model execution,
resume tailoring, real ATS form submission, outreach, or external Google service
synchronization. These features remain separate future release gates.

## User command

Configure a private board registry with public Greenhouse / Lever board tokens
as described in [PHASE-5-LIVE-DISCOVERY.md](PHASE-5-LIVE-DISCOVERY.md).

```bash
jobops review-live --sources /private/path/boards.json \
  --output /private/path/review-queue.json \
  --role-keyword "Staff Engineer" --role-keyword "Applied AI"
```

Optional `--ledger /private/path/jobops.db` records read-only discovery
artifacts and deduplicates across runs. Without a ledger, deduplication is
limited to one run. Only permitted public posting APIs are contacted. No
portal logins, application submission, or outreach sends are performed.

The queue contains source endpoint, source body SHA-256, fetch timestamp,
stable requisition identity, title and official hosted URL. The role term
score is **query overlap, not a candidate-fit, ATS or interview probability
score**. Every item is `Needs review` with explicit unresolved sponsorship,
work authorization, remote/travel, mandatory qualification and freshness
questions. It must not be reused as submission authorization.

## Release gates

| Gate | Evidence | Status |
|---|---|---|
| Offline read-only journey | `tests/test_review_queue_release.py` | Automatable |
| CLI install and smoke | Clean machine install | Pending |
| Allowed live board/terms review | Recorded provider docs, board authorization | Pending |
| Real live ATS smoke | Source URL, fetch trace, timestamp, known result | Pending |
| Third-party AI sandbox | Host-level enforcement | Pending |
| Resume document quality | Actual PDF and ATS evidence | Pending |
| External portals and duplicate-safe submissions | Authenticated browser acceptance | Pending |
| Schedule and connected account permissions | Durable end-to-end test | Pending |
| Independent security audit | Audited release candidate SHA | Pending |

**Release decision:** only the read-only review-first capability can
be considered for an experimental developer release following live-board
source compliance and clean install evidence. Do not claim full production
readiness, enable external submissions, or market unfinished providers as
operational.

Rollback: disable use of `review-live` and keep `JOBOPS_ALLOW_SUBMIT=0`,
`JOBOPS_ENABLE_LIVE_SUBMIT=0`, `JOBOPS_ENABLE_OUTREACH_SEND=0`.
