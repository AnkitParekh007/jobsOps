# JobOps marketing site

A lightweight six-page static site in `website/`: home, features, docs, search,
about and contact. It markets **the review-first developer preview**, not
unverified autonomous submissions. All documentation links target the canonical
GitHub repository.

## Development
```bash
python3 -m http.server 8080 --directory website
node --check website/assets/app.js
python3 website/tests/static_check.py
```
Open `http://localhost:8080/`. Use the search icon or `/` shortcut.
The first visit defaults to the light GoDocs-inspired palette; users can toggle dark mode, with preference saved locally.

## Validation
- CI checks six page routes, stable absolute external links, a JavaScript-disabled
  content fallback, minimum 4.5:1 primary CTA text contrast, JS syntax and CSP.
- Playwright Chromium checks desktop (1440px), mobile (390px and 320px),
  horizontal overflow, theme persistence, mobile menu Escape behavior, docs
  links, site search and keyboard shortcut. Screenshots are attached to CI.
- No credentials, analytics, browser automation against job portals, or
  application submission are present on the marketing site.

## Cloudflare Pages
See [CLOUDFLARE-PAGES.md](CLOUDFLARE-PAGES.md) for **review-only deployment
configuration**, necessary acceptance checks and explicit approval gates.
Do not connect the repo to Pages, change DNS, or publish before owner approval.

## Visual system and senior UX audit

Design direction based on the [GoDocs documentation website](https://dribbble.com/shots/10175793-GoDocs-Documentation-Website) by Themefisher. The exact palette anchors are #FBFBFB (canvas), #D70716 (primary), #A19FA1 (neutral), #0C1323 (text), #573C45 (wine), #E79FAB (rose) and #AB7D81 (muted rose). The design is a fresh JobOps implementation without copying illustrations or proprietary assets.

Audit-driven improvements: immediate above-the-fold documentation search, four high-level topic shortcuts, fewer ungrounded product metrics, stronger reading hierarchy, keyboard-search access, accessible native FAQ disclosures, improved navigation/current-page state, theme persistence and responsive topic cards. The mock queue is explicitly labeled illustrative. Safe, honest product positioning remains unchanged.

**Release workflow:** PR review → CI desktop/mobile screenshot review → merge → existing GitHub Pages workflow deploys `website/`. Do not change GitHub Pages source, custom domain, or DNS.
