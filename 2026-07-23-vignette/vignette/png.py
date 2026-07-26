"""From-scratch PNG encoder: chunk framing, CRC-32, and zlib-deflated
scanlines (using the stdlib `zlib` module for the DEFLATE bitstream itself,
same as every prior daily-build project that emits PNGs — the PNG container
format, filtering, and chunk/CRC framing below are hand-built)."""

import struct
import zlib

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(tag, data):
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def encode_png(image):
    """Encode `image` to PNG file bytes, in memory."""
    width, height = image.width, image.height
    raw = bytearray()
    prev = bytes(width * 3)
    for y in range(height):
        row = bytearray(width * 3)
        i = 0
        for x in range(width):
            r, g, b = image.get(x, y)
            row[i] = r
            row[i + 1] = g
            row[i + 2] = b
            i += 3
        # Paeth filter per scanline (filter type 4)
        out = bytearray(width * 3 + 1)
        out[0] = 4
        for x in range(width * 3):
            a = row[x - 3] if x >= 3 else 0
            b = prev[x]
            c = prev[x - 3] if x >= 3 else 0
            out[x + 1] = (row[x] - _paeth(a, b, c)) & 0xFF
        raw.extend(out)
        prev = bytes(row)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)

    return (
        _PNG_SIG
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


def save_png(image, path):
    with open(path, "wb") as f:
        f.write(encode_png(image))
