"""Minimal PNG encoder (truecolor, 8-bit) using only the stdlib."""

from __future__ import annotations

import struct
import zlib


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rgb: list[tuple[int, int, int]]) -> bytes:
    """Encode a row-major list of (r, g, b) pixels as a PNG byte string."""
    if len(rgb) != width * height:
        raise ValueError(f"expected {width * height} pixels, got {len(rgb)}")
    raw = bytearray()
    idx = 0
    for _ in range(height):
        raw.append(0)  # filter type: none
        for _ in range(width):
            raw.extend(rgb[idx])
            idx += 1
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
            _chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            _chunk(b"IEND", b""),
        ]
    )
