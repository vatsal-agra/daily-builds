"""Named colour palettes and mapping utilities."""
import math
import colorsys

def _lerp(a, b, t):
    return a + (b - a) * t

def _lerp_color(c0, c1, t):
    return (
        int(_lerp(c0[0], c1[0], t)),
        int(_lerp(c0[1], c1[1], t)),
        int(_lerp(c0[2], c1[2], t)),
    )

def _build_gradient(stops):
    """stops: list of (float_pos, (r,g,b)) sorted by pos."""
    def sample(t):
        t = max(0.0, min(1.0, t))
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]
            p1, c1 = stops[i + 1]
            if p0 <= t <= p1:
                s = (t - p0) / (p1 - p0) if p1 > p0 else 0.0
                return _lerp_color(c0, c1, s)
        return stops[-1][1]
    return sample

PALETTES = {
    "fire": _build_gradient([
        (0.0,  (0,   0,   0)),
        (0.25, (128, 0,   0)),
        (0.5,  (255, 64,  0)),
        (0.75, (255, 200, 0)),
        (1.0,  (255, 255, 200)),
    ]),
    "ice": _build_gradient([
        (0.0,  (0,   0,   32)),
        (0.3,  (0,   64,  128)),
        (0.7,  (64,  160, 220)),
        (1.0,  (240, 248, 255)),
    ]),
    "viridis": _build_gradient([
        (0.0,   (68,  1,   84)),
        (0.25,  (59,  82,  139)),
        (0.5,   (33,  145, 140)),
        (0.75,  (94,  201, 98)),
        (1.0,   (253, 231, 37)),
    ]),
    "plasma": _build_gradient([
        (0.0,   (13,  8,   135)),
        (0.25,  (126, 3,   168)),
        (0.5,   (204, 71,  120)),
        (0.75,  (248, 149, 64)),
        (1.0,   (240, 249, 33)),
    ]),
    "magma": _build_gradient([
        (0.0,   (0,   0,   4)),
        (0.25,  (81,  18,  124)),
        (0.5,   (183, 55,  121)),
        (0.75,  (252, 136, 99)),
        (1.0,   (252, 253, 191)),
    ]),
    "twilight": _build_gradient([
        (0.0,  (226, 217, 226)),
        (0.25, (122, 103, 163)),
        (0.5,  (25,  19,  63)),
        (0.75, (100, 51,  75)),
        (1.0,  (226, 217, 226)),
    ]),
    "ocean": _build_gradient([
        (0.0,  (0,   5,   30)),
        (0.3,  (0,   40,  120)),
        (0.6,  (0,   120, 200)),
        (0.85, (100, 210, 230)),
        (1.0,  (255, 255, 255)),
    ]),
    "forest": _build_gradient([
        (0.0,  (5,   20,  5)),
        (0.3,  (20,  80,  20)),
        (0.6,  (60,  150, 60)),
        (0.85, (160, 220, 80)),
        (1.0,  (240, 255, 180)),
    ]),
    "neon": _build_gradient([
        (0.0,  (0,   0,   0)),
        (0.2,  (0,   0,   200)),
        (0.4,  (180, 0,   255)),
        (0.6,  (0,   220, 200)),
        (0.8,  (255, 255, 0)),
        (1.0,  (255, 255, 255)),
    ]),
    "grayscale": _build_gradient([
        (0.0, (0,   0,   0)),
        (1.0, (255, 255, 255)),
    ]),
    "coolwarm": _build_gradient([
        (0.0,  (59,  76,  192)),
        (0.5,  (220, 220, 220)),
        (1.0,  (180, 4,   38)),
    ]),
    "sunset": _build_gradient([
        (0.0,  (10,  10,  40)),
        (0.3,  (120, 20,  80)),
        (0.6,  (220, 80,  20)),
        (0.85, (255, 200, 40)),
        (1.0,  (255, 240, 180)),
    ]),
}

PALETTE_NAMES = sorted(PALETTES.keys())


def sample_palette(name, t):
    """Return (r,g,b) tuple for t in [0,1]."""
    fn = PALETTES.get(name)
    if fn is None:
        raise ValueError(f"Unknown palette '{name}'. Available: {PALETTE_NAMES}")
    return fn(t)


def apply_palette(values, name="viridis", vmin=None, vmax=None, gamma=1.0):
    """Map a flat iterable of floats to a list of (r,g,b) tuples."""
    vals = list(values)
    lo = vmin if vmin is not None else min(vals)
    hi = vmax if vmax is not None else max(vals)
    span = hi - lo if hi != lo else 1.0
    fn = PALETTES.get(name)
    if fn is None:
        raise ValueError(f"Unknown palette '{name}'")
    result = []
    for v in vals:
        t = (v - lo) / span
        t = max(0.0, min(1.0, t))
        if gamma != 1.0:
            t = t ** gamma
        result.append(fn(t))
    return result


def hsv_cycle_palette(n, saturation=0.9, value=0.85, hue_offset=0.0):
    """n evenly-spaced hues → list of (r,g,b)."""
    result = []
    for i in range(n):
        h = (hue_offset + i / n) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, saturation, value)
        result.append((int(r * 255), int(g * 255), int(b * 255)))
    return result
