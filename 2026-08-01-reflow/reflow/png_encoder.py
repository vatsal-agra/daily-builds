"""A minimal, real PNG encoder: correct signature, IHDR/IDAT/IEND chunks,
per-chunk CRC-32, and zlib-deflated scanlines (filter type 0 / None per row).
Uses stdlib `zlib` and `struct` only -- no Pillow, no third-party imaging.
"""

import struct
import zlib

_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def _chunk(chunk_type, data):
    return (
        struct.pack('>I', len(data))
        + chunk_type
        + data
        + struct.pack('>I', zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def encode_rgb(pixels, width, height):
    """pixels: a flat list/bytes of RGB triples, row-major, length
    width*height*3. Returns real PNG file bytes."""
    if len(pixels) != width * height * 3:
        raise ValueError(
            f'expected {width * height * 3} bytes of RGB pixel data, got {len(pixels)}'
        )
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)

    raw = bytearray()
    row_bytes = width * 3
    for y in range(height):
        raw.append(0)  # filter type 0: None
        start = y * row_bytes
        raw.extend(pixels[start:start + row_bytes])

    idat = zlib.compress(bytes(raw), 9)

    return (
        _SIGNATURE
        + _chunk(b'IHDR', ihdr)
        + _chunk(b'IDAT', idat)
        + _chunk(b'IEND', b'')
    )


class Canvas:
    """A simple RGB raster surface with basic drawing primitives, used by
    the painter to rasterize a layout tree before encoding to PNG."""

    def __init__(self, width, height, background=(255, 255, 255)):
        self.width = max(1, width)
        self.height = max(1, height)
        self.pixels = bytearray(background * (self.width * self.height))

    def set_pixel(self, x, y, color):
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 3
            self.pixels[i] = color[0]
            self.pixels[i + 1] = color[1]
            self.pixels[i + 2] = color[2]

    def fill_rect(self, x, y, w, h, color):
        x0 = max(0, int(x))
        y0 = max(0, int(y))
        x1 = min(self.width, int(x + w))
        y1 = min(self.height, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.width + x0) * 3
            self.pixels[i:i + len(row)] = row

    def to_png(self):
        return encode_rgb(self.pixels, self.width, self.height)
