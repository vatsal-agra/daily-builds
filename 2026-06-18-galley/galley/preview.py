"""A tiny dependency-free PNG preview of a typeset paragraph.

Without a browser there is no way to rasterise the SVG, so Galley ships its own
minimal PNG encoder (zlib + CRC from the standard library only) and renders a
*greeked* preview: every word becomes a dark bar at its exact laid-out position.
Greeking is a real typographic technique — by removing the legible glyphs it
makes the *shape* of the text block obvious, so the evenness of Knuth--Plass
versus the ragged gaps of greedy jump out at a glance.
"""

from __future__ import annotations

import struct
import zlib
from typing import List, Tuple

from .render import layout_line


class Canvas:
    """A small 24-bit RGB raster with filled-rectangle drawing."""

    def __init__(self, width: int, height: int, bg=(251, 250, 247)):
        self.w = width
        self.h = height
        self.buf = bytearray()
        row = bytes(bg) * width
        for _ in range(height):
            self.buf += row

    def _put(self, x: int, y: int, color: Tuple[int, int, int]):
        if 0 <= x < self.w and 0 <= y < self.h:
            o = (y * self.w + x) * 3
            self.buf[o:o + 3] = bytes(color)

    def rect(self, x, y, w, h, color, *, alpha=1.0):
        x0, y0 = int(round(x)), int(round(y))
        x1, y1 = int(round(x + w)), int(round(y + h))
        for yy in range(max(0, y0), min(self.h, y1)):
            base = yy * self.w
            for xx in range(max(0, x0), min(self.w, x1)):
                o = (base + xx) * 3
                if alpha >= 1.0:
                    self.buf[o:o + 3] = bytes(color)
                else:
                    for k in range(3):
                        src = self.buf[o + k]
                        self.buf[o + k] = int(src * (1 - alpha) + color[k] * alpha)

    def to_png(self) -> bytes:
        # Add the mandatory per-scanline filter byte (0 = none).
        raw = bytearray()
        stride = self.w * 3
        for y in range(self.h):
            raw.append(0)
            raw += self.buf[y * stride:(y + 1) * stride]
        comp = zlib.compress(bytes(raw), 9)

        def chunk(tag, data):
            c = tag + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", comp)
                + chunk(b"IEND", b""))


_HEAT = [
    (0.0, (26, 152, 80)), (15.0, (102, 189, 99)), (40.0, (166, 217, 106)),
    (80.0, (254, 224, 139)), (150.0, (253, 174, 97)), (400.0, (244, 109, 67)),
    (1e11, (215, 48, 39)),
]


def _heat(bad):
    for t, c in _HEAT:
        if bad <= t:
            return c
    return (215, 48, 39)


def _draw_paragraph(canvas, items, breaking, font, measure, ox, oy,
                    leading, scale, heat):
    bar_h = max(2, int(font.size * 0.62 * scale))
    pad = (leading - bar_h) / 2.0
    for li, line in enumerate(breaking.lines):
        y = oy + li * leading
        if heat:
            canvas.rect(ox, y, measure * scale, leading, _heat(line.badness), alpha=0.22)
        runs, _ = layout_line(items, line)
        for x, _text, w in runs:
            canvas.rect(ox + x * scale, y + pad, w * scale, bar_h, (38, 36, 32))
    return oy + len(breaking.lines) * leading


def comparison_png(items, kp, greedy, font, measure, *, scale=2.0,
                   path=None) -> bytes:
    """Render a side-by-side greeked PNG: Knuth--Plass (top) vs greedy (bottom)."""
    leading = font.size * 1.34 * scale
    margin = 22.0
    label_h = 26.0
    col_w = measure * scale
    width = int(col_w + 2 * margin)
    kp_h = len(kp.lines) * leading
    gr_h = len(greedy.lines) * leading
    height = int(2 * margin + 2 * label_h + kp_h + gr_h + margin)
    cv = Canvas(width, height)

    def rule(oy, h):
        cv.rect(margin - 1, oy, 1, h, (226, 220, 205))
        cv.rect(margin + col_w, oy, 1, h, (226, 220, 205))
        # accent tick where greedy's ragged edge would fall is implicit in bars

    y = margin + label_h
    cv.rect(margin, y - label_h + 6, 60, 4, (240, 180, 41))  # KP accent
    rule(y, kp_h)
    y = _draw_paragraph(cv, items, kp, font, measure, margin, y, leading, scale, True)
    y += margin + label_h
    cv.rect(margin, y - label_h + 6, 60, 4, (215, 48, 39))   # greedy accent
    rule(y, gr_h)
    _draw_paragraph(cv, items, greedy, font, measure, margin, y, leading, scale, True)

    data = cv.to_png()
    if path:
        with open(path, "wb") as fh:
            fh.write(data)
    return data
