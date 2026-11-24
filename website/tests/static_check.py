#!/usr/bin/env python3
"""Static site acceptance without network/browser."""
from html.parser import HTMLParser
from pathlib import Path
import re

SITE = Path(__file__).resolve().parents[1]
ROUTES = ["index", "features", "docs", "about", "contact", "search"]


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.main = 0
        self.title = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "main":
            self.main += 1
        if tag == "title":
            self.title += 1
        if attrs.get("id"):
            assert attrs["id"] not in self.ids, ("duplicate id", attrs["id"])
            self.ids.add(attrs["id"])


def luminance(color):
    v = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)]
    return sum(w*(c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4)
               for w, c in zip((.2126, .7152, .0722), v))


def check():
    for name in ROUTES:
        html = (SITE / f"{name}.html").read_text()
        parser = Parser()
        parser.feed(html)
        assert parser.main == parser.title == 1, name
        for required in ["<noscript>", 'assets/theme-init.js', 'assets/favicon.svg',
                         'assets/styles.css', 'assets/app.js', '<meta name="description"']:
            assert required in html, (name, required)
    js = (SITE / "assets/app.js").read_text()
    assert 'const repo="https://github.com/AnkitParekh007/jobsOps"' in js
    assert '"url":"AnkitParekh007/' not in js
    assert "closeMenu()" in js
    assert "Needs review" in js and "submissions and outreach are off" in js
    css = (SITE / "assets/styles.css").read_text()
    found = re.search(r"background:linear-gradient\(110deg,(#[a-f0-9]{6}),(#[a-f0-9]{6})\)",css)
    assert found, "primary gradient missing"
    for color in found.groups():
        assert 1.05/(luminance(color)+.05) >= 4.5, ("AA contrast fails", color)
    for filename in ["_headers", "404.html", "assets/theme-init.js",
                     "assets/favicon.svg", "CLOUDFLARE-PAGES.md"]:
        assert (SITE / filename).is_file(), filename
    policy = (SITE / "_headers").read_text()
    assert "Content-Security-Policy:" in policy and "script-src 'self'" in policy
    print("PASS 6 pages + external links + contrast + theme + fallback + deployment metadata")


if __name__ == "__main__":
    check()
