# Architecture visuals

Self-contained HTML/CSS motion companions to the Mermaid diagrams in the README and wiki. The **main README** embeds animated GIF previews (GitHub-safe) that link to the interactive HTML pages.

| File | Purpose |
|---|---|
| [index.html](index.html) | Gallery entry |
| [pipeline-dag.html](pipeline-dag.html) | Animated harness / DAG (full motion) |
| [trust-boundary.html](trust-boundary.html) | Animated trust planes (full motion) |
| [shared.css](shared.css) | Shared tokens, type, atmosphere, motion |
| [previews/pipeline-dag.gif](previews/pipeline-dag.gif) | README-inline pipeline capture |
| [previews/trust-boundary.gif](previews/trust-boundary.gif) | README-inline trust-boundary capture |
| [previews/generate_previews.py](previews/generate_previews.py) | Regenerates the GIF captures (Pillow) |

## Preview

```bash
# from repo root — interactive HTML
open docs/visuals/index.html
# or
python3 -m http.server 8765
# then visit http://127.0.0.1:8765/docs/visuals/
```

On GitHub, README shows the GIFs automatically. Locally, open the HTML for CSS/JS motion.

```bash
# regenerate GIF previews (optional; needs Pillow)
PYTHONPATH=/path/to/pillow python3 docs/visuals/previews/generate_previews.py
# then optionally compress with ffmpeg paletteuse
```

Aesthetic: night operations console (Oxanium + IBM Plex, signal teal / gate amber on ink). Submit and outreach remain **off** in all copy. Not a production-readiness claim.
