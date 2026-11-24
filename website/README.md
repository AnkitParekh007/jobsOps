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

## Support card

The homepage includes an optional supporter section based on the creator-provided screenshot. It links to the confirmed Buy Me a Coffee profile at https://buymeacoffee.com/ankitparekh and the official GitHub repository for stars and contributions. A GitHub Sponsors payment destination is intentionally not advertised until its active profile is confirmed. The card is responsive, theme-aware, keyboard-friendly and does not load external scripts or collect payment details.

## Identity and floating navigation refresh

The header follows the owner's DailyToolsOps [navigation implementation](https://github.com/AnkitParekh007/DailyToolsOps/blob/main/website/style.css): sticky floating card with a bordered, softly translucent surface, compact desktop links, collapsible mobile navigation, search shortcut (slash or Ctrl/Cmd+K), GitHub link and three-option System/Light/Dark theme control. JobOps retains its own terminology and content.

The logo is a new geometric **J + O + check** monogram in JobOps navy, red and muted rose rather than the earlier briefcase-orbit icon. The SVG is used consistently in the header, footer and favicon, and has no external assets. The unmerged logo proposal PR #13 is superseded by this direction.
