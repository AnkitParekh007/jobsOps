#!/usr/bin/env python3
"""Browser acceptance: desktop/mobile routes, search, theme, menu and no-JS."""
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import functools
import json
import threading

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parents[1]
OUT = Path("website-audit")
ROUTES = ["index", "features", "docs", "about", "contact", "search"]


def run():
    OUT.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0),
        functools.partial(SimpleHTTPRequestHandler, directory=str(SITE)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    results = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox"])
            try:
                for width in [1440, 390, 320]:
                    context = browser.new_context(viewport={"width": width, "height": 850},
                                                  color_scheme="dark", reduced_motion="reduce")
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    for route in ROUTES:
                        response = page.goto(f"{origin}/{route}.html", wait_until="networkidle")
                        assert response and response.status == 200, (route, "not_found")
                        assert page.locator("main h1").count() == 1, (route, "missing_heading")
                        delta = page.evaluate("document.documentElement.scrollWidth - innerWidth")
                        assert delta <= 1, (route, width, "horizontal_overflow", delta)
                        assert not errors, (route, errors)
                        results.append({"route": route, "width": width, "overflow": delta})
                        if route == "index":
                            page.screenshot(path=str(OUT / f"home-{width}.png"), full_page=True)
                    page.goto(f"{origin}/search.html", wait_until="networkidle")
                    page.locator("#searchbox").fill("security")
                    assert page.locator(".result").count() >= 1, "search_empty"
                    page.goto(f"{origin}/index.html", wait_until="networkidle")
                    assert page.locator("html").get_attribute("data-theme") == "light"
                    assert page.locator("form.hero-search[role=search]").count() == 1
                    assert page.locator(".topic-card").count() == 4
                    assert page.locator(".faq-item").count() == 4
                    assert page.locator(".support-panel").count() == 1
                    coffee = page.locator("a.support-coffee")
                    assert coffee.count() == 1
                    assert coffee.get_attribute("href") == "https://buymeacoffee.com/ankitparekh"
                    assert coffee.get_attribute("target") == "_blank"
                    assert "noopener" in coffee.get_attribute("rel")
                    github = page.locator("a.support-github")
                    assert github.get_attribute("href") == "https://github.com/AnkitParekh007/jobsOps"
                    assert github.get_attribute("target") == "_blank"
                    if width == 1440:
                        first = coffee.bounding_box()
                        second = github.bounding_box()
                        assert first and second
                        assert abs(first["y"] - second["y"]) <= 3, "desktop support CTAs must share a row"
                    page.locator("#theme").click()
                    assert page.locator("html").get_attribute("data-theme") == "dark"
                    if width == 1440:
                        page.screenshot(path=str(OUT / "home-dark-1440.png"), full_page=True)
                    page.reload(wait_until="networkidle")
                    assert page.locator("html").get_attribute("data-theme") == "dark"
                    page.locator("#theme").click()
                    assert page.locator("html").get_attribute("data-theme") == "light"
                    if width == 1440:
                        page.screenshot(path=str(OUT / "home-light-1440.png"), full_page=True)
                    page.locator("#hero-query").fill("discovery")
                    page.locator(".hero-search button").click()
                    page.wait_for_url("**/search.html?q=discovery")
                    assert page.locator(".result").count() >= 1
                    if width <= 700:
                        menu = page.locator("#menu")
                        assert menu.is_visible()
                        menu.click()
                        assert menu.get_attribute("aria-expanded") == "true"
                        page.keyboard.press("Escape")
                        assert menu.get_attribute("aria-expanded") == "false"
                        assert not page.locator("#links").is_visible()
                    page.goto(f"{origin}/docs.html", wait_until="networkidle")
                    links = page.locator('a[href*="/blob/main/"]').evaluate_all(
                        "(a) => a.map(x => x.getAttribute('href'))")
                    assert len(links) >= 10, "documentation_links_missing"
                    assert all(url.startswith("https://github.com/AnkitParekh007/jobsOps/")
                               for url in links), links
                    page.goto(f"{origin}/index.html", wait_until="networkidle")
                    page.keyboard.press("/")
                    page.wait_for_url("**/search.html")
                    assert page.locator("#searchbox").is_visible()
                    context.close()
                no_js = browser.new_context(java_script_enabled=False)
                page = no_js.new_page()
                page.goto(f"{origin}/index.html")
                assert page.locator("main h1").is_visible(), "no_js_fallback_missing"
                no_js.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    print(f"PASS {len(results)} browser route/viewport cases + search/theme/mobile/keyboard")


if __name__ == "__main__":
    run()
