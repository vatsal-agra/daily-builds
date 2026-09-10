"""A from-scratch PNG encoder: RGBA pixel buffer -> real PNG file bytes.
No PIL/Pillow/imaging library. Uses stdlib `zlib` for DEFLATE compression
and `zlib.crc32` for chunk checksums (the same "no imaging library, zlib
for the compressed stream only" pattern this repo's Prism/Atlasforge/
Morphica builds established) and a hand-written chunk framer + Sub filter,
matching the real PNG spec byte-for-byte (any real viewer opens the output)."""

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class Canvas:
    """A simple RGBA raster surface with basic drawing primitives."""

    def __init__(self, width, height, background=(255, 255, 255, 255)):
        self.width = max(int(width), 1)
        self.height = max(int(height), 1)
        self.pixels = bytearray(self.width * self.height * 4)
        for i in range(0, len(self.pixels), 4):
            self.pixels[i:i + 4] = bytes(background)

    def _blend(self, idx, color):
        r, g, b, a = color
        if a >= 255:
            self.pixels[idx:idx + 4] = bytes((r, g, b, 255))
            return
        if a <= 0:
            return
        dr, dg, db, da = self.pixels[idx:idx + 4]
        af = a / 255.0
        nr = int(r * af + dr * (1 - af))
        ng = int(g * af + dg * (1 - af))
        nb = int(b * af + db * (1 - af))
        self.pixels[idx:idx + 4] = bytes((nr, ng, nb, 255))

    def set_pixel(self, x, y, color):
        x, y = int(x), int(y)
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = (y * self.width + x) * 4
            self._blend(idx, color)

    def fill_rect(self, x, y, w, h, color):
        if color[3] <= 0 or w <= 0 or h <= 0:
            return
        x0, y0 = max(int(round(x)), 0), max(int(round(y)), 0)
        x1, y1 = min(int(round(x + w)), self.width), min(int(round(y + h)), self.height)
        for yy in range(y0, y1):
            row = yy * self.width
            for xx in range(x0, x1):
                self._blend((row + xx) * 4, color)

    def hline(self, x, y, length, thickness, color):
        self.fill_rect(x, y, length, thickness, color)

    def vline(self, x, y, length, thickness, color):
        self.fill_rect(x, y, thickness, length, color)

    def to_png_bytes(self):
        return encode_png(self.width, self.height, bytes(self.pixels))


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))


def encode_png(width, height, rgba_bytes):
    """rgba_bytes: width*height*4 raw bytes, row-major, top-to-bottom."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        row = rgba_bytes[y * stride:(y + 1) * stride]
        raw.append(1)  # filter type 1 = Sub
        prev = bytearray(4)
        filtered = bytearray(stride)
        for i in range(stride):
            a = row[i - 4] if i >= 4 else 0
            filtered[i] = (row[i] - a) & 0xFF
        raw += filtered
    idat = zlib.compress(bytes(raw), 9)
    out = bytearray()
    out += PNG_SIGNATURE
    out += _chunk(b"IHDR", ihdr)
    out += _chunk(b"IDAT", idat)
    out += _chunk(b"IEND", b"")
    return bytes(out)


def decode_png(data):
    """Minimal decoder (RGBA, non-interlaced, filter types 0/1/2/3/4) used
    only by the test suite to round-trip-verify the encoder."""
    assert data[:8] == PNG_SIGNATURE
    i = 8
    width = height = 0
    bit_depth = color_type = 0
    idat = bytearray()
    while i < len(data):
        length = struct.unpack(">I", data[i:i + 4])[0]
        tag = data[i + 4:i + 8]
        chunk_data = data[i + 8:i + 8 + length]
        if tag == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk_data[:10])
        elif tag == b"IDAT":
            idat += chunk_data
        elif tag == b"IEND":
            break
        i += 8 + length + 4
    assert bit_depth == 8 and color_type == 6, "decoder only supports 8-bit RGBA"
    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    out = bytearray(width * height * 4)
    prev_row = bytearray(stride)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        pos += 1
        row = bytearray(raw[pos:pos + stride])
        pos += stride
        for x in range(stride):
            a = row[x - 4] if x >= 4 else 0
            b = prev_row[x]
            c = prev_row[x - 4] if x >= 4 else 0
            if ftype == 0:
                pass
            elif ftype == 1:
                row[x] = (row[x] + a) & 0xFF
            elif ftype == 2:
                row[x] = (row[x] + b) & 0xFF
            elif ftype == 3:
                row[x] = (row[x] + (a + b) // 2) & 0xFF
            elif ftype == 4:
                row[x] = (row[x] + _paeth(a, b, c)) & 0xFF
        out[y * stride:(y + 1) * stride] = row
        prev_row = row
    return width, height, bytes(out)


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c
