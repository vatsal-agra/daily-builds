"""Grayscale raster image, barcode rendering, and realistic degradations (blur, noise, ink gain, rotation...)."""
import math
import random

from . import png


class Image:
    def __init__(self, width, height, fill=255, rows=None):
        self.w, self.h = width, height
        self.rows = rows if rows is not None else [bytearray([fill]) * width for _ in range(height)]

    @classmethod
    def load(cls, path):
        w, h, rows = png.load(path)
        return cls(w, h, rows=rows)

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.to_png())

    def to_png(self):
        return png.encode_gray(self.rows, self.w, self.h)

    def copy(self):
        return Image(self.w, self.h, rows=[bytearray(r) for r in self.rows])

    def get(self, x, y):
        """Bilinear sample; out-of-range returns white."""
        if x < 0 or y < 0 or x > self.w - 1 or y > self.h - 1:
            return 255.0
        x0, y0 = int(x), int(y)
        x1, y1 = min(x0 + 1, self.w - 1), min(y0 + 1, self.h - 1)
        fx, fy = x - x0, y - y0
        r0, r1 = self.rows[y0], self.rows[y1]
        top = r0[x0] * (1 - fx) + r0[x1] * fx
        bot = r1[x0] * (1 - fx) + r1[x1] * fx
        return top * (1 - fy) + bot * fy


# ---------------------------------------------------------------- rendering
def render(barcode, module=3, height=80, quiet=None, margin_y=10):
    """Render a Barcode to an Image: integer module width in px, bar height in px."""
    q = barcode.quiet if quiet is None else quiet
    mods = barcode.modules
    w = (len(mods) + 2 * q) * module
    row = bytearray([255]) * w
    for i, ch in enumerate(mods):
        if ch == "1":
            x0 = (q + i) * module
            row[x0:x0 + module] = bytes([0]) * module
    h = height + 2 * margin_y
    rows = []
    for y in range(h):
        rows.append(bytearray(row) if margin_y <= y < margin_y + height else bytearray([255]) * w)
    return Image(w, h, rows=rows)


def render_subpixel(barcode, module=2.6, height=80, quiet=None, margin_y=10, gain=0.0):
    """Render with fractional module width and ink gain (px each bar edge moves outward)
    using exact area coverage — produces realistic anti-aliased edges."""
    q = barcode.quiet if quiet is None else quiet
    mods = barcode.modules
    w = int(math.ceil((len(mods) + 2 * q) * module))
    cov = [0.0] * w
    runs, x = [], q * module
    i = 0
    while i < len(mods):
        j = i
        while j < len(mods) and mods[j] == mods[i]:
            j += 1
        if mods[i] == "1":
            runs.append((q * module + i * module - gain, q * module + j * module + gain))
        i = j
    for a, b in runs:
        a, b = max(a, 0), min(b, w)
        px = int(a)
        while px < b and px < w:
            lo, hi = max(a, px), min(b, px + 1)
            if hi > lo:
                cov[px] += hi - lo
            px += 1
    row = bytearray(int(round(255 * (1 - min(1.0, c)))) for c in cov)
    h = height + 2 * margin_y
    rows = [bytearray(row) if margin_y <= y < margin_y + height else bytearray([255]) * w for y in range(h)]
    return Image(w, h, rows=rows)


# ---------------------------------------------------------------- degradations
def blur(img, sigma):
    """Separable Gaussian blur."""
    if sigma <= 0:
        return img.copy()
    r = max(1, int(math.ceil(3 * sigma)))
    k = [math.exp(-(i * i) / (2 * sigma * sigma)) for i in range(-r, r + 1)]
    s = sum(k); k = [v / s for v in k]
    w, h = img.w, img.h
    tmp = []
    for row in img.rows:
        pad = [row[0]] * r + list(row) + [row[-1]] * r
        tmp.append([sum(k[j] * pad[x + j] for j in range(2 * r + 1)) for x in range(w)])
    out = [bytearray(w) for _ in range(h)]
    for y in range(h):
        for x in range(w):
            acc = 0.0
            for j in range(-r, r + 1):
                yy = min(h - 1, max(0, y + j))
                acc += k[j + r] * tmp[yy][x]
            out[y][x] = int(acc + 0.5)
    return Image(w, h, rows=out)


def noise(img, sigma, seed=0):
    rnd = random.Random(seed)
    out = []
    for row in img.rows:
        out.append(bytearray(min(255, max(0, int(v + rnd.gauss(0, sigma) + 0.5))) for v in row))
    return Image(img.w, img.h, rows=out)


def contrast(img, lo=60, hi=200):
    """Squash the dynamic range to [lo, hi] (washed-out print)."""
    out = [bytearray(lo + (hi - lo) * v // 255 for v in row) for row in img.rows]
    return Image(img.w, img.h, rows=out)


def illumination(img, strength=0.5):
    """Left-to-right lighting falloff (shadow gradient), multiplicative."""
    out = []
    for row in img.rows:
        out.append(bytearray(int(v * (1 - strength * x / max(1, img.w - 1))) for x, v in enumerate(row)))
    return Image(img.w, img.h, rows=out)


def rotate(img, degrees, fill=255):
    """Rotate about centre by `degrees` (counter-clockwise on screen), expanding the canvas."""
    a = math.radians(degrees)
    ca, sa = math.cos(a), math.sin(a)
    nw = int(math.ceil(abs(img.w * ca) + abs(img.h * sa)))
    nh = int(math.ceil(abs(img.w * sa) + abs(img.h * ca)))
    cx, cy, ncx, ncy = img.w / 2, img.h / 2, nw / 2, nh / 2
    out = []
    for y in range(nh):
        row = bytearray(nw)
        dy = y - ncy
        for x in range(nw):
            dx = x - ncx
            sx = cx + dx * ca - dy * sa
            sy = cy + dx * sa + dy * ca
            if sx < 0 or sy < 0 or sx > img.w - 1 or sy > img.h - 1:
                row[x] = fill
            else:
                row[x] = int(img.get(sx, sy) + 0.5)
        out.append(row)
    return Image(nw, nh, rows=out)


def flip_h(img):
    return Image(img.w, img.h, rows=[bytearray(r[::-1]) for r in img.rows])


def paste(canvas, img, x0, y0):
    for y in range(img.h):
        yy = y0 + y
        if 0 <= yy < canvas.h:
            for x in range(img.w):
                xx = x0 + x
                if 0 <= xx < canvas.w:
                    canvas.rows[yy][xx] = img.rows[y][x]


def add_clutter(canvas, seed=0, count=12):
    """Draw random dark text-like blobs/lines so the scanner must locate the barcode among junk."""
    rnd = random.Random(seed)
    for _ in range(count):
        x0, y0 = rnd.randrange(canvas.w), rnd.randrange(canvas.h)
        w, h = rnd.randrange(4, 40), rnd.randrange(2, 9)
        for y in range(y0, min(canvas.h, y0 + h)):
            for x in range(x0, min(canvas.w, x0 + w)):
                canvas.rows[y][x] = min(canvas.rows[y][x], 40)
