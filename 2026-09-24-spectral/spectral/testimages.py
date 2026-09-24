"""Procedural synthetic test images, so the whole suite is self-contained
and reproducible without depending on any external sample photo.
"""
import math
import random

from .colorspace import Image


def gradient(width=64, height=64):
    """Smooth diagonal color gradient -- almost all low-frequency energy,
    the case JPEG compresses best."""
    r = [0] * (width * height)
    g = [0] * (width * height)
    b = [0] * (width * height)
    for y in range(height):
        for x in range(width):
            i = y * width + x
            r[i] = int(255 * x / max(1, width - 1))
            g[i] = int(255 * y / max(1, height - 1))
            b[i] = int(255 * (x + y) / max(1, width + height - 2))
    return Image(width, height, r, g, b)


def checkerboard(width=64, height=64, cell=8):
    """Sharp high-frequency edges -- the case that stresses quantization
    and block artifacts the hardest."""
    r = [0] * (width * height)
    g = [0] * (width * height)
    b = [0] * (width * height)
    for y in range(height):
        for x in range(width):
            i = y * width + x
            on = ((x // cell) + (y // cell)) % 2 == 0
            v = 235 if on else 20
            r[i] = g[i] = b[i] = v
    return Image(width, height, r, g, b)


def radial_target(width=64, height=64):
    """Concentric rings -- a mix of frequencies radiating from the center,
    useful for seeing ringing artifacts around sharp circular edges."""
    r = [0] * (width * height)
    g = [0] * (width * height)
    b = [0] * (width * height)
    cx, cy = width / 2.0, height / 2.0
    for y in range(height):
        for x in range(width):
            i = y * width + x
            d = math.hypot(x - cx, y - cy)
            ring = int(127.5 + 127.5 * math.sin(d * 0.6))
            r[i] = ring
            g[i] = 255 - ring
            b[i] = int(127.5 + 127.5 * math.cos(d * 0.3))
    return Image(width, height, r, g, b)


def synthetic_photo(width=96, height=96, seed=1234):
    """A synthetic 'photo-like' scene: a smoothly-shaded sky-like
    background, a few flat-colored 'object' rectangles with soft edges,
    and speckled sensor-noise texture -- the mix of smooth regions, hard
    edges, and high-frequency noise a real photograph has, without
    needing an actual external image file."""
    rng = random.Random(seed)
    r = [0] * (width * height)
    g = [0] * (width * height)
    b = [0] * (width * height)

    for y in range(height):
        for x in range(width):
            i = y * width + x
            t = y / max(1, height - 1)
            r[i] = int(40 + 120 * t)
            g[i] = int(80 + 100 * t)
            b[i] = int(150 + 90 * (1 - t))

    rects = [
        (width * 0.15, height * 0.55, width * 0.35, height * 0.85, 200, 60, 40),
        (width * 0.45, height * 0.35, width * 0.75, height * 0.70, 40, 160, 70),
        (width * 0.60, height * 0.10, width * 0.90, height * 0.30, 230, 200, 40),
    ]
    for (x0, y0, x1, y1, cr, cg, cb) in rects:
        for y in range(int(y0), int(y1)):
            for x in range(int(x0), int(x1)):
                i = y * width + x
                edge = min(x - x0, x1 - x, y - y0, y1 - y)
                mix = min(1.0, edge / 3.0) if edge >= 0 else 0.0
                r[i] = int(r[i] * (1 - mix) + cr * mix)
                g[i] = int(g[i] * (1 - mix) + cg * mix)
                b[i] = int(b[i] * (1 - mix) + cb * mix)

    for i in range(width * height):
        n = rng.randint(-8, 8)
        r[i] = max(0, min(255, r[i] + n))
        g[i] = max(0, min(255, g[i] + n))
        b[i] = max(0, min(255, b[i] + n))

    return Image(width, height, r, g, b)


def solid(width=32, height=32, color=(128, 64, 200)):
    n = width * height
    return Image(width, height, [color[0]] * n, [color[1]] * n, [color[2]] * n)


ALL_GENERATORS = {
    "gradient": gradient,
    "checkerboard": checkerboard,
    "radial": radial_target,
    "photo": synthetic_photo,
    "solid": solid,
}
