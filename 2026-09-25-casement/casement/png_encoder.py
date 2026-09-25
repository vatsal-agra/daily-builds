"""A minimal from-scratch PNG encoder for an RGBA framebuffer.

Writes the PNG chunk structure (signature, IHDR, IDAT, IEND) and per-scanline
filtering by hand; uses `zlib` only for the DEFLATE compression stream itself
and CRC-32, exactly as this repo's other from-scratch renderers do (e.g.
Prism's PNG encoder) -- the PNG *format* is implemented here, not borrowed.
"""

import struct
import zlib


def _chunk(tag, data):
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_rgba(width, height, pixels):
    """`pixels` is a flat bytearray/bytes of length width*height*4 (RGBA)."""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter type 0: None
        raw += pixels[y * stride:(y + 1) * stride]
    compressed = zlib.compress(bytes(raw), level=9)

    out = bytearray(b"\x89PNG\r\n\x1a\n")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    out += _chunk(b"IHDR", ihdr)
    out += _chunk(b"IDAT", compressed)
    out += _chunk(b"IEND", b"")
    return bytes(out)


def save(path, width, height, pixels):
    with open(path, "wb") as f:
        f.write(encode_rgba(width, height, pixels))
