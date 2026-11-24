# JobOps Marketing Website — React / Vite

This is the React migration of the *existing* JobOps marketing site, isolated from the Python CLI.
The original **website/** remains untouched until the React implementation has passed review.

## Existing pages and preserved routes

- `/` and `/index.html` — homepage
- `/features.html` — feature status
- `/docs.html` — guide library
- `/about.html` — project mission
- `/contact.html` — issues, discussion, security reporting
- `/search.html` — documentation search
- `/404.html` — genuine GitHub Pages 404 response

## Run locally

Requires Node 22+.

```bash
cd web-react
npm install
npm run dev
# Open http://localhost:5173/jobsOps/
```

## Build and preview

```bash
cd web-react
npm test
npm run build
npm run preview
# http://localhost:4173/jobsOps/
```

`npm run build` compiles Vite, **pre-renders HTML for six routes with ReactDOMServer** and validates SEO, sitemap, canonical URLs, assets, pre-rendered H1 and 404. The HTML page content is present in the initial server-generated response and hydrated in the browser, so search-engine crawlers do not need JavaScript to see the content. Source content remains in `src/data/legacyContent.js`, mechanically extracted from `website/assets/app.js`. It is parsed into React nodes; no arbitrary user HTML is supported. Repeated header/footer, cards, SEO and navigation are reusable React components.

## GitHub Pages

The **GitHub repository** is `AnkitParekh007/jobsOps`. Therefore **Vite base = `/jobsOps/`** and canonical origin = `https://ankitparekh007.github.io/jobsOps/`. The path `/DailyToolsOps/` belongs to a different repository and must not be used for JobOps.

The existing `.github/workflows/deploy-marketing-pages.yml` is changed to install dependencies in `web-react/`, build `web-react/dist/`, then publish that directory using official GitHub Pages actions. Merge only after PR review and CI acceptance; merging to main triggers deployment. Never change DNS/custom domains as part of this migration.

Existing `.html` URLs have **physical pre-rendered files**, so direct visits and refreshes work on Pages without a SPA redirect hack. Unknown URLs return static `404.html` with HTTP 404.

## SEO and content maintenance

- Edit `src/data/seo.js` for titles, descriptions, canonical/OG/Twitter data and JSON-LD.
- Update `public/sitemap.xml` and `public/robots.txt` when public routes change.
- `public/assets/social-preview.svg` is a **placeholder** sharing asset. Replace with a tested 1200×630 PNG for broadest social crawler compatibility.
- To add a new page, create a page component in `src/pages/`, add a Route in `src/App.jsx`, add a metadata entry, extend the pre-render list, and update the sitemap. New documentation/tool topics go in `src/data/legacyContent.js` after a separate content review, or a new source data module.
- `src/components/LegacyMarkup.jsx` converts reviewed, repository-owned content to React nodes and React Router links. Once parity is verified, page sections can be incrementally moved into dedicated JSX components.
- Original stylesheet source is copied into `src/styles/`; design and layout changes should go through the same PR tests.
- Never add candidate secrets, applicant identities, job portal tokens or submission capabilities to public marketing code.

## Quality gates

`npm test` asserts source parity and correct canonical URLs. The React CI workflow runs Vite production build, HTML/SEO verification, and Playwright Chromium on desktop + 390px/320px mobile. It also checks working navigation, theme, search, logo, direct routes and HTTP 404. The Python app CI remains separate.

## Migration limitations

Content preservation is intentionally prioritized over redesign: the source page templates are parsed into React components at runtime *and* server-rendered at build time. Full hand conversion of each editorial paragraph to JSX can happen later without changing the HTML output. The original HTML has not been deleted.
