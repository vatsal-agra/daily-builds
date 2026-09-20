"""A hand-rolled PNG encoder: builds real IHDR/IDAT/IEND chunks with a
correct CRC-32 trailer on each, over an explicit per-scanline filter step
("None" filter, byte 0) -- Python's `zlib` module is used only for the
DEFLATE *compressed-stream framing* inside IDAT, the same narrow use every
other from-scratch PNG encoder in this repo's history (Prism, Lumina,
Morphica, Galley, Vignette) makes; Folio still does 100% of the actual
drawing (every pixel's RGB value) itself in `raster.py`.
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


def encode_png(pixels, width, height):
    """`pixels` is a flat bytearray/bytes of RGB triples, row-major,
    length == width * height * 3."""
    if len(pixels) != width * height * 3:
        raise ValueError(
            f"pixel buffer length {len(pixels)} != {width}x{height}x3"
        )

    raw = bytearray()
    stride = width * 3
    for row in range(height):
        raw.append(0)  # filter type 0: None
        start = row * stride
        raw.extend(pixels[start:start + stride])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=9)

    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out.extend(_chunk(b"IHDR", ihdr))
    out.extend(_chunk(b"IDAT", idat))
    out.extend(_chunk(b"IEND", b""))
    return bytes(out)


def save_png(path, pixels, width, height):
    with open(path, "wb") as f:
        f.write(encode_png(pixels, width, height))
