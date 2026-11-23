# Phase 5 — Live public ATS discovery (review-only)

This focused implementation adds a **read-only public posting API workflow** independent of
unattended AI agents. It does not authorize external application submission or outreach.

## Configuration

The registry is deliberately user-supplied (no personalized employers in public git):

```json
{
  "sources": [
    {"provider": "greenhouse", "board": "company-board-token", "organization": "Example Company"},
    {"provider": "lever", "board": "company-site-name", "organization": "Example Company"}
  ]
}
```

Accepted providers: `greenhouse`, `lever`, `lever_eu`. Only verified public ATS API
hosts are queried, with bounded GET requests through `safe_http_fetch` (SSRF, redirects
and connection-time IP validation). Sites need to permit API access; respect provider terms,
rate limits and takedown requests. No generic crawling, scraping or search-engine discovery.

```bash
jobops discover-live --sources "$HOME/jobops-sources.json" \
  --output "$HOME/jobops-live-report.json" \
  --ledger "$HOME/.local/share/jobops/state/jobops.db"
```

On macOS use your private Application Support path instead of the Linux path above.
The registry must explicitly list board tokens. The CLI never submits applications or sends email.

## Evidence and status

Each accepted posting includes ATS provider/board/requisition identity, canonical hosted job
URL, source endpoint, UTC fetch timestamp, HTTP-listing evidence, and SHA-256 of the
source response. `availability=open` means *present in a public ATS listing at fetch*,
not guaranteed open indefinitely. Every posting is `Needs review` until independent
candidate work authorization, mandatory skills, sponsorship and remote/onsite constraints
are checked. Do not convert this feed directly to `Eligible` or `Applied`.

Source statuses: `blocked` for network/HTTP/invalid feed, `partial` for truncation or
invalid rows, `exhausted` only for a successful empty authoritative feed, otherwise
`complete`. A failed source is never marked exhausted. Optional private SQLite
ledger persistence deduplicates across runs, and each posting has a stable ATS identity.

## Acceptance and limitations

Run `python -m pytest tests/test_live_discovery_phase5.py -q` and the full CI.
Tests are offline and synthetic, with no live network and no real submissions.
This PR alone **does not** establish live provider availability, verified
posting freshness after collection, authenticated portal access, eligibility, or
production readiness. An opt-in real board smoke test and source compliance review
are required before using a specific provider board for production discovery.
