#!/usr/bin/env python3
"""Build exclusion URL index from local tracker CSV exports (if present)."""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path


URL_RE = re.compile(r"https?://[^\s,\"']+")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: build_exclusion_index.py <exports_dir> <out.json>", file=sys.stderr)
        return 2
    exports = Path(sys.argv[1])
    out = Path(sys.argv[2])
    urls: set[str] = set()
    files_used: list[str] = []

    if exports.is_dir():
        for path in sorted(exports.glob("*.csv")):
            files_used.append(path.name)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # Prefer csv parse; fall back to regex.
            try:
                reader = csv.DictReader(text.splitlines())
                for row in reader:
                    for val in row.values():
                        if not val:
                            continue
                        for m in URL_RE.finditer(val):
                            u = m.group(0).split("?")[0].rstrip("/")
                            if "docs.google.com" in u or "drive.google.com" in u:
                                continue
                            urls.add(u)
            except Exception:  # noqa: BLE001
                for m in URL_RE.finditer(text):
                    u = m.group(0).split("?")[0].rstrip("/")
                    if "docs.google.com" in u or "drive.google.com" in u:
                        continue
                    urls.add(u)

    payload = {
        "canonical_urls": sorted(urls),
        "count": len(urls),
        "source_files": files_used,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "count": len(urls), "files": len(files_used)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
