# Cloudflare Pages — review-first marketing site deployment

The GitHub PR only prepares hosting. **Do not create a Pages project, attach a domain, update DNS, or start a production deployment without owner review.**

## Current site
- Repo: `AnkitParekh007/jobsOps`
- Site source: `website/` (fully static HTML/CSS/JS; no build necessary)
- Pages / navigation: `index.html`, `features.html`, `docs.html`, `search.html`, `about.html`, `contact.html`; custom `404.html`
- Public release claims: **review-first developer preview**. Live applications and outreach remain disabled.

## Cloudflare Pages Git integration — proposed settings

In Cloudflare dashboard: **Workers & Pages → Create application → Pages → Connect to Git**.
After selecting the GitHub repository:

| Setting | Value |
|---|---|
| Framework preset | None |
| Production branch | `main` **after PR review/merge only** |
| Root directory (advanced) | Repository root (leave blank) |
| Build command | Leave empty / none |
| Build output directory | `website` |
| Environment variables | None needed |
| Custom domain | **Leave unconfigured** until separately approved |
| Automatic production deploy | Do not enable before approving the publish step |

**Important:** Depending on Cloudflare's Git-integration flow, connecting an existing repo may start an initial deployment. Do not complete the connection flow until owner explicitly approves going live. For approval-only review, use PR branch code and CI without creating the Pages project.

Cloudflare Pages processes the `website/_headers` file as response-header rules. Test CSP, X-Frame-Options, no-analytics assumptions and the site's actual deployed headers before production. Review the policy if introducing third-party scripts, forms, analytics or fonts.

## Acceptance checklist

- [ ] Owner reviews and merges PR
- [ ] Marketing-site CI passes (syntax, source links, route, theme, search, narrow-screen)
- [ ] Desktop/mobile screenshots reviewed and keyboard-only navigation tested
- [ ] Verify light and dark theme, remembered preference, search and slash shortcut
- [ ] Verify mobile menu and Escape/close interactions
- [ ] Verify all six routes, 404 route, favicon and internal/external links on deployment URL
- [ ] Verify Cloudflare's actual CSP/security headers in browser devtools/network panel
- [ ] Verify GitHub release/README links point to the intended project and no fictional submission claims
- [ ] Separate explicit owner approval to connect Pages or publish
- [ ] Separate explicit approval for any custom-domain or DNS change

## Rollback

Disable Pages automatic deploy and revert the site commit on the hosting branch. This marketing site is isolated from Python JobOps runtime and does not grant any application-submission permission.

References:
- https://developers.cloudflare.com/pages/get-started/git-integration/
- https://developers.cloudflare.com/pages/configuration/build-configuration/
- https://developers.cloudflare.com/pages/configuration/headers/
