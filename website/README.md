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
Theme respects the OS choice, is toggleable and is persisted locally.

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
