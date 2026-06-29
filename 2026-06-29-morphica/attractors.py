"""
Strange attractor renderers.

Each attractor is integrated and projected to 2-D.  A histogram accumulator
tallies how many orbit points land in each pixel; colour is log-scaled density
mapped through a palette (flame-algorithm style).
"""
import math
import random as _random


# ── integrators ───────────────────────────────────────────────────────────────

def _lorenz(x, y, z, sigma=10.0, rho=28.0, beta=8.0 / 3.0, dt=0.005):
    dx = sigma * (y - x)
    dy = x * (rho - z) - y
    dz = x * y - beta * z
    return x + dx * dt, y + dy * dt, z + dz * dt


def _rossler(x, y, z, a=0.2, b=0.2, c=5.7, dt=0.01):
    dx = -(y + z)
    dy = x + a * y
    dz = b + z * (x - c)
    return x + dx * dt, y + dy * dt, z + dz * dt


def _clifford(x, y, a=-1.4, b=1.6, c=1.0, d=0.7):
    nx = math.sin(a * y) + c * math.cos(a * x)
    ny = math.sin(b * x) + d * math.cos(b * y)
    return nx, ny


def _dejong(x, y, a=1.641, b=1.902, c=0.316, d=1.525):
    nx = math.sin(a * y) - math.cos(b * x)
    ny = math.sin(c * x) - math.cos(d * y)
    return nx, ny


def _pickover(x, y, z, a=-2.24, b=0.43, c=-0.65, d=-2.43):
    nx = math.sin(a * y) - z * math.cos(b * x)
    ny = z * math.sin(c * x) - math.cos(d * y)
    nz = math.sin(x)
    return nx, ny, nz


def _duffing(x, y, a=2.75, b=0.2):
    # Duffing map: x_{n+1} = y_n, y_{n+1} = -b*x_n + a*y_n - y_n^3
    nx = y
    ny = -b * x + a * y - y ** 3
    return nx, ny


# ── attractor registry ────────────────────────────────────────────────────────

ATTRACTORS = {
    "lorenz": {
        "description": "Lorenz butterfly (sigma=10, rho=28, beta=8/3)",
        "dims": 3,
        "project": "xz",   # which axes to plot
        "warmup": 1000,
        "steps": 2_000_000,
    },
    "rossler": {
        "description": "Rössler attractor (a=0.2, b=0.2, c=5.7)",
        "dims": 3,
        "project": "xy",
        "warmup": 500,
        "steps": 1_000_000,
    },
    "clifford": {
        "description": "Clifford attractor map (a=-1.4, b=1.6, c=1.0, d=0.7)",
        "dims": 2,
        "warmup": 100,
        "steps": 2_000_000,
    },
    "dejong": {
        "description": "De Jong attractor (a=1.641, b=1.902, c=0.316, d=1.525)",
        "dims": 2,
        "warmup": 100,
        "steps": 2_000_000,
    },
    "pickover": {
        "description": "Pickover attractor (3-D → xy projection)",
        "dims": 3,
        "project": "xy",
        "warmup": 200,
        "steps": 1_000_000,
    },
    "duffing": {
        "description": "Duffing oscillator map (a=2.75, b=0.2)",
        "dims": 2,
        "warmup": 100,
        "steps": 500_000,
    },
}

ATTRACTOR_NAMES = sorted(ATTRACTORS.keys())


# ── histogram accumulator ─────────────────────────────────────────────────────

def _accumulate(xs, ys, width, height, margin=20):
    """Map (xs, ys) lists to a histogram array.  Returns flat list of counts."""
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    xspan = xmax - xmin or 1.0
    yspan = ymax - ymin or 1.0
    hist = [0] * (width * height)
    aw = width - 2 * margin
    ah = height - 2 * margin
    for px, py in zip(xs, ys):
        col = int(margin + (px - xmin) / xspan * aw)
        row = int(margin + (py - ymin) / yspan * ah)
        col = max(margin, min(width - margin - 1, col))
        row = max(margin, min(height - margin - 1, row))
        hist[row * width + col] += 1
    return hist


def _hist_to_pixels(hist, palette_fn, bg=(10, 10, 10)):
    """Log-scale histogram → (r,g,b) pixel list."""
    max_count = max(hist) or 1
    log_max = math.log1p(max_count)
    pixels = []
    for count in hist:
        if count == 0:
            pixels.append(bg)
        else:
            t = math.log1p(count) / log_max
            pixels.append(palette_fn(t))
    return pixels


# ── orbit generators ──────────────────────────────────────────────────────────

def _orbit_lorenz(steps, warmup, seed):
    rng = _random.Random(seed)
    x, y, z = rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(20, 30)
    for _ in range(warmup):
        x, y, z = _lorenz(x, y, z)
    xs, ys = [], []
    for _ in range(steps):
        x, y, z = _lorenz(x, y, z)
        xs.append(x)
        ys.append(z)   # project xz
    return xs, ys


def _orbit_rossler(steps, warmup, seed):
    rng = _random.Random(seed)
    x, y, z = rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0, 1)
    for _ in range(warmup):
        x, y, z = _rossler(x, y, z)
    xs, ys = [], []
    for _ in range(steps):
        x, y, z = _rossler(x, y, z)
        xs.append(x)
        ys.append(y)
    return xs, ys


def _orbit_clifford(steps, warmup, seed):
    rng = _random.Random(seed)
    x, y = rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5)
    for _ in range(warmup):
        x, y = _clifford(x, y)
    xs, ys = [], []
    for _ in range(steps):
        x, y = _clifford(x, y)
        xs.append(x)
        ys.append(y)
    return xs, ys


def _orbit_dejong(steps, warmup, seed):
    rng = _random.Random(seed)
    x, y = rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5)
    for _ in range(warmup):
        x, y = _dejong(x, y)
    xs, ys = [], []
    for _ in range(steps):
        x, y = _dejong(x, y)
        xs.append(x)
        ys.append(y)
    return xs, ys


def _orbit_pickover(steps, warmup, seed):
    rng = _random.Random(seed)
    x, y, z = rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)
    for _ in range(warmup):
        x, y, z = _pickover(x, y, z)
    xs, ys = [], []
    for _ in range(steps):
        x, y, z = _pickover(x, y, z)
        xs.append(x)
        ys.append(y)
    return xs, ys


def _orbit_duffing(steps, warmup, seed):
    rng = _random.Random(seed)
    # Use small initial conditions to stay in the basin of attraction
    x, y = rng.uniform(-0.1, 0.1), rng.uniform(-0.1, 0.1)
    # Guard against divergence — skip if |x| or |y| > 10
    for _ in range(warmup):
        nx, ny = _duffing(x, y)
        if abs(nx) > 10 or abs(ny) > 10:
            x, y = 0.01, 0.01
        else:
            x, y = nx, ny
    xs, ys = [], []
    for _ in range(steps):
        nx, ny = _duffing(x, y)
        if abs(nx) > 10 or abs(ny) > 10:
            x, y = 0.01, 0.01
        else:
            x, y = nx, ny
            xs.append(x)
            ys.append(y)
    return xs, ys


_ORBIT_FNS = {
    "lorenz":   _orbit_lorenz,
    "rossler":  _orbit_rossler,
    "clifford": _orbit_clifford,
    "dejong":   _orbit_dejong,
    "pickover": _orbit_pickover,
    "duffing":  _orbit_duffing,
}


# ── public API ────────────────────────────────────────────────────────────────

def render_attractor(
    name,
    width=800,
    height=800,
    steps=None,
    seed=None,
    palette_fn=None,
    bg=(10, 10, 10),
):
    """
    Render a named strange attractor.

    Returns flat list of (r,g,b) tuples, width, height.
    """
    if name not in ATTRACTORS:
        raise ValueError(f"Unknown attractor '{name}'. Available: {ATTRACTOR_NAMES}")
    cfg = ATTRACTORS[name]
    n_steps = steps if steps is not None else cfg["steps"]
    warmup = cfg["warmup"]
    orbit_fn = _ORBIT_FNS[name]
    xs, ys = orbit_fn(n_steps, warmup, seed)
    hist = _accumulate(xs, ys, width, height)
    if palette_fn is None:
        from palette import PALETTES
        palette_fn = PALETTES["plasma"]
    pixels = _hist_to_pixels(hist, palette_fn, bg=bg)
    return pixels, width, height
