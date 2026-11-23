#!/usr/bin/env python3
"""
Deterministic PDF fixture builder + lightweight text extraction.

Generates real ``%PDF`` documents with extractable text (no LaTeX toolchain).
Used by materials/identity tests; live authorize still recomputes SHA-256.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Sequence


def fingerprint_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_text_pdf(pages: Sequence[str]) -> bytes:
    """
    Build a minimal multi-page PDF with one text line per page (Helvetica).
    Page order is preserved for extraction tests.
    """
    if not pages:
        raise ValueError("pdf_fixture_requires_pages")
    objs: list[bytes] = []
    # 1: Catalog, 2: Pages, then per-page Page+Content, then Font
    font_id = 3 + len(pages) * 2

    def obj(n: int, body: bytes) -> bytes:
        return f"{n} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages)))
    objs.append(obj(1, "<< /Type /Catalog /Pages 2 0 R >>".encode("ascii")))
    objs.append(
        obj(
            2,
            f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"),
        )
    )
    for i, text in enumerate(pages):
        page_id = 3 + i * 2
        content_id = page_id + 1
        safe = (
            text.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("\r", " ")
            .replace("\n", " ")
        )
        # Keep ASCII-ish for the fixture; drop non-latin1.
        safe = safe.encode("latin-1", errors="replace").decode("latin-1")
        stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET\n".encode("latin-1")
        objs.append(
            obj(
                page_id,
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Contents {content_id} 0 R "
                    f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
                ).encode("ascii"),
            )
        )
        objs.append(
            obj(
                content_id,
                f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
                + stream
                + b"endstream",
            )
        )
    objs.append(
        obj(
            font_id,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        )
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for body in objs:
        offsets.append(len(out))
        out.extend(body)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


def write_text_pdf(path: Path, pages: Sequence[str]) -> tuple[str, bytes]:
    raw = build_text_pdf(pages)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return fingerprint_bytes(raw), raw


_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_TJ_RE = re.compile(rb"\((?:\\.|[^\\)])*\)\s*Tj")


def extract_text_simple(data: bytes) -> list[str]:
    """
    Extract ``(text) Tj`` strings in document order (page/stream order).
    Does not require pypdf.
    """
    pages: list[str] = []
    for match in _STREAM_RE.finditer(data):
        stream = match.group(1)
        parts: list[str] = []
        for tj in _TJ_RE.finditer(stream):
            raw = tj.group(0)
            # strip trailing " Tj"
            lit = raw[: raw.rfind(b")") + 1]
            inner = lit[1:-1]
            text = (
                inner.replace(b"\\(", b"(")
                .replace(b"\\)", b")")
                .replace(b"\\\\", b"\\")
                .decode("latin-1", errors="replace")
            )
            parts.append(text)
        if parts:
            pages.append(" ".join(parts))
    return pages


def extract_text_ordered(path: Path) -> tuple[str, list[str]]:
    raw = Path(path).read_bytes()
    pages = extract_text_simple(raw)
    return "\n".join(pages), pages
