#!/usr/bin/env python3
"""Build per-worker prompt markdown files for the discovery harness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--worker-template", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--shards-dir", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--exclusion", required=True)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    tmpl = Path(args.worker_template).read_text(encoding="utf-8")
    run_dir = Path(args.run_dir)
    shards = Path(args.shards_dir)
    excl = Path(args.exclusion)
    default_mode = manifest.get("mode", "http")
    run_dir.mkdir(parents=True, exist_ok=True)
    shards.mkdir(parents=True, exist_ok=True)

    for w in manifest["workers"]:
        shard_id = w["shard_id"]
        shard_path = shards / f"{shard_id}.json"
        target = int(w.get("target_matches", 15))
        mode = w.get("mode", default_mode)
        body = (
            tmpl.replace("SHARD_OUT_PATH", str(shard_path))
            .replace("RUN_ID", args.run_id)
            .replace("TARGET_MATCHES", str(target))
        )
        inject = f"""# Discovery WORKER prompt (not frontier)

## Assignment (harness)

- shard_id: `{shard_id}`
- run_id: `{args.run_id}`
- lane: `{w["lane"]}` ({w["lane_name"]})
- country: `{w["country"]}`
- mode: `{mode}` — if `http`, browser/Playwright/computer-use/Chrome DevTools MCP/browser-use MCP are **forbidden**
- query_titles: {json.dumps(w["query_titles"])}
- preferred_sources: {json.dumps(w["sources"])}
- target_matches: {target}
- exclusion_index: `{excl}`
- shard_output: `{shard_path}`

Read the exclusion index JSON and skip those canonical URLs.
HTTP only — prefer Greenhouse / Ashby / Lever public JSON or HTML via curl/WebFetch first. Never launch a browser MCP.
Every match **must** have non-empty `reason` and non-empty `evidence_quote` (quote from fetched body). Omit matches that lack either.
Stop once you reach about {target} real matches or sources are exhausted.
When done, the shard file must exist. Print SHARD_OK and exit.
"""
        out = run_dir / f"prompt-worker-{shard_id}.md"
        out.write_text(inject + "\n" + body + "\n", encoding="utf-8")
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
