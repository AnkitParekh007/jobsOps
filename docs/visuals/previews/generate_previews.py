#!/usr/bin/env python3
"""Generate GitHub-safe animated GIF previews for README embedding.

Requires Pillow. Run from repo root or this directory:
  PYTHONPATH=/path/to/pillow python3 docs/visuals/previews/generate_previews.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
W, H = 1120, 420
FPS_DELAY = 80  # ms
FRAMES = 36

INK = (7, 11, 16)
PANEL = (14, 21, 29)
MIST = (197, 212, 224)
STEEL = (91, 124, 148)
SIGNAL = (46, 230, 166)
AMBER = (240, 162, 2)
CORAL = (255, 107, 90)
VAULT = (126, 200, 255)
TEXT = (232, 240, 246)


def font(size: int, mono: bool = False):
    candidates = (
        [
            "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
            "/System/Library/Fonts/Menlo.ttc",
            "/Library/Fonts/SF-Mono-Medium.otf",
        ]
        if mono
        else [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def lerp(a, b, t):
    return a + (b - a) * t


def draw_bg(img: Image.Image, w: int, h: int):
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle((0, 0, w, h), fill=(*INK, 255))
    # soft wells
    for cx, cy, r, color, alpha in (
        (140, 40, 220, SIGNAL, 28),
        (980, 80, 180, AMBER, 22),
        (860, 360, 200, VAULT, 20),
    ):
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for i in range(8, 0, -1):
            rr = int(r * i / 8)
            a = int(alpha * (1 - i / 8))
            od.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(*color, a))
        img.alpha_composite(overlay)
    draw = ImageDraw.Draw(img, "RGBA")
    # grid
    for x in range(0, w, 48):
        draw.line((x, 0, x, h), fill=(18, 28, 38, 255))
    for y in range(0, h, 48):
        draw.line((0, y, w, y), fill=(18, 28, 38, 255))
    return draw


def rounded(draw, box, fill, outline, radius=8, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pulse(t: float, phase: float = 0.0) -> float:
    return 0.5 + 0.5 * math.sin((t + phase) * math.pi * 2)


def pipeline_frame(t: float) -> Image.Image:
    img = Image.new("RGBA", (W, H), (*INK, 255))
    draw = draw_bg(img, W, H)

    f_title = font(22)
    f_mono = font(13, mono=True)
    f_small = font(12, mono=True)
    f_tiny = font(11)

    draw.text((28, 18), "jobsOps", fill=SIGNAL, font=f_title)
    draw.text((130, 24), "PIPELINE / DAG", fill=STEEL, font=f_mono)
    badge = (920, 18, 1090, 46)
    rounded(draw, badge, (40, 28, 8, 180), AMBER, radius=4)
    draw.text((932, 24), "SUBMIT / OUTREACH OFF", fill=AMBER, font=f_small)

    stages = [
        ("01", "Context", "F01"),
        ("02", "Exclusion", "index"),
        ("03", "Workers", "F02"),
        ("04", "Merge", "ingest"),
        ("05", "Verify", "F03"),
        ("06", "Rank", "F04"),
    ]
    active = int(t * len(stages)) % len(stages)
    x0, y0, bw, bh, gap = 28, 70, 160, 70, 18
    for i, (sid, name, hint) in enumerate(stages):
        x = x0 + i * (bw + gap)
        glow = pulse(t, i / len(stages)) if i == active else 0.15
        outline = (
            int(lerp(STEEL[0], SIGNAL[0], glow)),
            int(lerp(STEEL[1], SIGNAL[1], glow)),
            int(lerp(STEEL[2], SIGNAL[2], glow)),
        )
        fill = (18, 27, 38, 230)
        rounded(draw, (x, y0, x + bw, y0 + bh), fill, outline, radius=8, width=2)
        if i == active:
            # scan shimmer
            sx = x + int((bw + 20) * ((t * 3) % 1.0)) - 10
            draw.rectangle((sx, y0 + 2, sx + 18, y0 + bh - 2), fill=(46, 230, 166, 35))
        draw.text((x + 12, y0 + 10), sid, fill=SIGNAL, font=f_small)
        draw.text((x + 12, y0 + 28), name, fill=TEXT, font=f_mono)
        draw.text((x + 12, y0 + 48), hint, fill=STEEL, font=f_tiny)

    # flow nodes lower
    nodes = [
        (60, 200, 130, 54, "Trigger", "schedule", SIGNAL),
        (230, 200, 130, 54, "F01", "preflight", SIGNAL),
        (400, 200, 130, 54, "F02", "discover", SIGNAL),
        (570, 200, 130, 54, "Verify", "eligible?", SIGNAL),
        (760, 280, 140, 54, "Needs review", "unclear", AMBER),
        (570, 280, 140, 54, "Hard miss", "skip", CORAL),
        (400, 280, 130, 54, "F04 Rank", "shortlist", SIGNAL),
        (230, 280, 130, 54, "Gate", "SUBMIT OFF", AMBER),
        (470, 350, 200, 48, "F10 Ledger + report", "finalize", VAULT),
    ]

    # edges (simple lines with dash offset)
    edges = [
        ((125, 227), (230, 227), SIGNAL),
        ((295, 227), (400, 227), SIGNAL),
        ((465, 227), (570, 227), SIGNAL),
        ((635, 254), (635, 280), AMBER),
        ((635, 254), (570, 280), CORAL),
        ((570, 227), (465, 280), SIGNAL),
        ((400, 307), (360, 307), SIGNAL),
        ((295, 307), (360, 374), VAULT),
        ((830, 307), (670, 374), VAULT),
        ((640, 307), (600, 374), VAULT),
    ]
    dash_off = int(t * 24) % 12
    for (x1, y1), (x2, y2), color in edges:
        # dashed polyline approximation
        steps = 16
        for s in range(steps):
            if (s + dash_off) % 3 == 0:
                continue
            u0, u1 = s / steps, (s + 1) / steps
            draw.line(
                (
                    lerp(x1, x2, u0),
                    lerp(y1, y2, u0),
                    lerp(x1, x2, u1),
                    lerp(y1, y2, u1),
                ),
                fill=(*color, 200),
                width=2,
            )

    for x, y, w, h, title, sub, color in nodes:
        rounded(draw, (x, y, x + w, y + h), (18, 27, 38, 240), color, radius=7, width=2)
        draw.text((x + 10, y + 10), title, fill=MIST, font=f_small)
        draw.text((x + 10, y + 30), sub, fill=STEEL, font=f_tiny)

    draw.text(
        (28, H - 28),
        "Preview capture · open interactive HTML for full motion",
        fill=STEEL,
        font=f_tiny,
    )
    return img


def trust_frame(t: float) -> Image.Image:
    img = Image.new("RGBA", (W, H), (*INK, 255))
    draw = draw_bg(img, W, H)

    f_title = font(22)
    f_mono = font(13, mono=True)
    f_small = font(12, mono=True)
    f_tiny = font(11)
    f_zone = font(16)

    draw.text((28, 18), "jobsOps", fill=SIGNAL, font=f_title)
    draw.text((130, 24), "TRUST BOUNDARY", fill=STEEL, font=f_mono)
    badge = (920, 18, 1090, 46)
    rounded(draw, badge, (40, 28, 8, 180), AMBER, radius=4)
    draw.text((932, 24), "SUBMIT / OUTREACH OFF", fill=AMBER, font=f_small)

    # zones
    zones = [
        (28, 70, 320, 300, "UNTRUSTED DATA", "Inbound fog", CORAL, [
            "Job postings / HTML",
            "Email bodies",
            "Agent prompts / outputs",
            "Provider CLIs",
        ]),
        (400, 70, 360, 300, "TRUSTED CONTROL PLANE", "Deterministic core", SIGNAL, [
            "Policy engine",
            "SQLite ledger",
            "ToolBroker + Sandbox",
            "Approval gate",
            "ControlPlaneController",
        ]),
        (820, 70, 272, 300, "PRIVATE", "JOBOPS_HOME", VAULT, [
            "Secrets · profile · history",
        ]),
    ]

    for i, (x, y, w, h, kicker, title, color, chips) in enumerate(zones):
        rounded(draw, (x, y, x + w, y + h), (12, 18, 26, 235), (*color, 160), radius=12, width=2)
        draw.text((x + 16, y + 16), kicker, fill=color, font=f_small)
        draw.text((x + 16, y + 40), title, fill=TEXT, font=f_zone)
        for j, chip in enumerate(chips):
            cy = y + 78 + j * 38
            appear = min(1.0, max(0.0, (t * 1.4) - j * 0.08 - i * 0.05))
            alpha = int(40 + 180 * appear)
            rounded(
                draw,
                (x + 16, cy, x + w - 16, cy + 30),
                (7, 11, 16, alpha),
                (*color, int(80 + 100 * appear)),
                radius=5,
                width=1,
            )
            draw.text((x + 26, cy + 7), chip, fill=(*MIST, int(80 + 175 * appear)), font=f_tiny)

        # particles in untrusted
        if i == 0:
            for p in range(5):
                px = x + 30 + int((80 + p * 35 + t * 90) % (w - 60))
                py = y + 100 + int(40 * math.sin(t * math.pi * 2 + p))
                draw.ellipse((px, py, px + 5, py + 5), fill=(*CORAL, 160))

    # membranes
    def membrane(x, y, h, colors, label, phase):
        rounded(draw, (x, y, x + 36, y + h), (10, 16, 20, 220), colors[0], radius=18, width=1)
        py = y + int((h + 40) * ((t + phase) % 1.0)) - 20
        draw.rectangle((x + 4, py, x + 32, py + 28), fill=(*colors[0], 90))
        # vertical label letters
        for li, ch in enumerate(label):
            draw.text((x + 12, y + 24 + li * 11), ch, fill=MIST, font=f_tiny)

    membrane(352, 78, 284, (SIGNAL, CORAL), "NEVER→INSTR", 0.0)
    membrane(772, 78, 284, (VAULT, SIGNAL), "PRIVATE", 0.35)

    # callouts
    callouts = [
        (CORAL, "DENY", "Postings / emails / model text are data — not authorization."),
        (SIGNAL, "GATE", "Policy + approval only; submit & outreach default OFF."),
        (VAULT, "STRIP", "JOBOPS_HOME secrets never inherited into provider CLIs."),
    ]
    for i, (color, tag, copy) in enumerate(callouts):
        x = 28 + i * 365
        y = 382
        rounded(draw, (x, y, x + 350, y + 28), (12, 18, 26, 230), (*color, 120), radius=4)
        draw.text((x + 8, y + 7), tag, fill=color, font=f_small)
        draw.text((x + 58, y + 8), copy, fill=STEEL, font=f_tiny)

    return img


def save_gif(name: str, frame_fn):
    rgb_frames = [frame_fn(i / FRAMES).convert("RGB") for i in range(FRAMES)]
    # Shared palette reduces flicker across frames.
    base = rgb_frames[0].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    frames = [base] + [
        frame.quantize(palette=base, dither=Image.Dither.NONE) for frame in rgb_frames[1:]
    ]
    path = OUT / name
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=FPS_DELAY,
        loop=0,
        optimize=False,
        disposal=2,
    )
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")


def main():
    save_gif("pipeline-dag.gif", pipeline_frame)
    save_gif("trust-boundary.gif", trust_frame)


if __name__ == "__main__":
    main()
