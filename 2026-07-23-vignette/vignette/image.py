"""Minimal RGB image container, PPM (P6) I/O, and procedural test images.

No PIL, no numpy — pixels are a flat list of (r, g, b) int triples in
row-major order. Kept simple on purpose: this module's only job is to get
pixels in and out so the codec itself can be the from-scratch part.
"""

import math
import struct


class Image:
    def __init__(self, width, height, pixels=None):
        self.width = width
        self.height = height
        if pixels is None:
            pixels = [(0, 0, 0)] * (width * height)
        if len(pixels) != width * height:
            raise ValueError(
                f"pixel count {len(pixels)} != width*height {width * height}"
            )
        self.pixels = pixels

    def get(self, x, y):
        x = min(max(x, 0), self.width - 1)
        y = min(max(y, 0), self.height - 1)
        return self.pixels[y * self.width + x]

    def set(self, x, y, rgb):
        self.pixels[y * self.width + x] = rgb

    def copy(self):
        return Image(self.width, self.height, list(self.pixels))

    def crop(self, x0, y0, w, h):
        out = []
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                out.append(self.get(x, y))
        return Image(w, h, out)

    # -- PPM (P6, binary) --------------------------------------------------

    def save_ppm(self, path):
        with open(path, "wb") as f:
            f.write(f"P6\n{self.width} {self.height}\n255\n".encode("ascii"))
            buf = bytearray(self.width * self.height * 3)
            i = 0
            for (r, g, b) in self.pixels:
                buf[i] = r
                buf[i + 1] = g
                buf[i + 2] = b
                i += 3
            f.write(bytes(buf))

    @staticmethod
    def load_ppm(path):
        with open(path, "rb") as f:
            data = f.read()
        if data[:2] != b"P6":
            raise ValueError("not a binary PPM (P6) file")
        pos = 2
        vals = []
        while len(vals) < 3:
            while data[pos] in b" \t\r\n":
                pos += 1
            if data[pos:pos + 1] == b"#":
                while data[pos] not in b"\r\n":
                    pos += 1
                continue
            start = pos
            while data[pos] not in b" \t\r\n":
                pos += 1
            vals.append(int(data[start:pos]))
        pos += 1  # single whitespace byte after maxval
        width, height, maxval = vals
        if maxval != 255:
            raise ValueError("only maxval=255 PPM supported")
        raw = data[pos:pos + width * height * 3]
        pixels = [
            (raw[i], raw[i + 1], raw[i + 2])
            for i in range(0, len(raw), 3)
        ]
        return Image(width, height, pixels)


# -- procedural test-image generators --------------------------------------


def gradient(width, height):
    px = []
    for y in range(height):
        for x in range(width):
            r = int(255 * x / max(width - 1, 1))
            g = int(255 * y / max(height - 1, 1))
            b = int(255 * (x + y) / max(width + height - 2, 1))
            px.append((r, g, b))
    return Image(width, height, px)


def checkerboard(width, height, cell=16):
    px = []
    for y in range(height):
        for x in range(width):
            on = ((x // cell) + (y // cell)) % 2 == 0
            px.append((235, 235, 235) if on else (20, 20, 30))
    return Image(width, height, px)


def circles(width, height):
    px = [(0, 0, 0)] * (width * height)
    centers = [
        (width * 0.3, height * 0.35, min(width, height) * 0.22, (220, 60, 60)),
        (width * 0.65, height * 0.3, min(width, height) * 0.18, (60, 160, 220)),
        (width * 0.5, height * 0.7, min(width, height) * 0.28, (250, 200, 60)),
    ]
    for y in range(height):
        for x in range(width):
            r, g, b = 15, 15, 25
            for (cx, cy, rad, color) in centers:
                d = math.hypot(x - cx, y - cy)
                if d < rad:
                    edge = min(1.0, (rad - d) / 6.0)
                    r = int(r * (1 - edge) + color[0] * edge)
                    g = int(g * (1 - edge) + color[1] * edge)
                    b = int(b * (1 - edge) + color[2] * edge)
            px[y * width + x] = (r, g, b)
    return Image(width, height, px)


def plasma(width, height, seed=1):
    # Deterministic pseudo-photographic texture: sum of sine fields at
    # different frequencies/phases, seeded so results are reproducible.
    def rnd(n):
        # tiny deterministic PRNG (LCG) so this file has zero external deps
        n = (1103515245 * n + 12345 + seed * 7919) & 0x7FFFFFFF
        return n

    s = seed
    terms = []
    for i in range(6):
        s = rnd(s + i)
        fx = 0.02 + (s % 1000) / 15000.0
        s = rnd(s)
        fy = 0.02 + (s % 1000) / 15000.0
        s = rnd(s)
        phase = (s % 6283) / 1000.0
        terms.append((fx, fy, phase))

    px = []
    for y in range(height):
        for x in range(width):
            v = 0.0
            for k, (fx, fy, phase) in enumerate(terms):
                v += math.sin(x * fx + y * fy * 0.7 + phase) * (1.0 / (k + 1))
            v = (v + 3.0) / 6.0
            v = min(max(v, 0.0), 1.0)
            r = int(60 + 180 * v)
            g = int(40 + 160 * (1 - abs(v - 0.5) * 2))
            b = int(200 - 140 * v)
            px.append((min(r, 255), min(g, 255), min(b, 255)))
    return Image(width, height, px)


def text_bars(width, height):
    # High-frequency horizontal stripes with a sharp diagonal edge — the
    # kind of content that stresses block-transform coding (ringing near
    # sharp edges, need for high-frequency coefficients).
    px = []
    for y in range(height):
        for x in range(width):
            stripe = 245 if (y // 3) % 2 == 0 else 15
            edge = 255 if x > width * 0.5 + (y - height / 2) * 0.3 else 0
            v = (stripe + edge) // 2
            px.append((v, v, v))
    return Image(width, height, px)


TEST_IMAGES = {
    "gradient": gradient,
    "checkerboard": checkerboard,
    "circles": circles,
    "plasma": plasma,
    "textbars": text_bars,
}
