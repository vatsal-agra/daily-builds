"""Synthetic 2-D datasets for binary classification.

Each generator returns ``(X, y)`` where X is a list of [x0, x1] float pairs and y
is a list of 0/1 int labels. All are deterministic given a seed and genuinely
non-linearly separable (so a linear model fails and an MLP is required).
"""

from __future__ import annotations

import math
import random


def _shuffle(X, y, rng):
    idx = list(range(len(X)))
    rng.shuffle(idx)
    return [X[i] for i in idx], [y[i] for i in idx]


def xor(n: int = 200, noise: float = 0.1, seed: int = 0):
    rng = random.Random(seed)
    X, y = [], []
    for _ in range(n):
        a = rng.choice([-1.0, 1.0])
        b = rng.choice([-1.0, 1.0])
        x0 = a + rng.gauss(0, noise)
        x1 = b + rng.gauss(0, noise)
        label = 1 if (a > 0) ^ (b > 0) else 0
        X.append([x0, x1])
        y.append(label)
    return _shuffle(X, y, rng)


def moons(n: int = 200, noise: float = 0.15, seed: int = 0):
    rng = random.Random(seed)
    X, y = [], []
    half = n // 2
    for i in range(half):
        t = math.pi * i / max(half - 1, 1)
        X.append([math.cos(t) + rng.gauss(0, noise),
                  math.sin(t) + rng.gauss(0, noise)])
        y.append(0)
    for i in range(n - half):
        t = math.pi * i / max(n - half - 1, 1)
        X.append([1 - math.cos(t) + rng.gauss(0, noise),
                  0.5 - math.sin(t) + rng.gauss(0, noise)])
        y.append(1)
    return _shuffle(X, y, rng)


def circles(n: int = 200, noise: float = 0.08, seed: int = 0):
    rng = random.Random(seed)
    X, y = [], []
    half = n // 2
    for i in range(half):
        t = 2 * math.pi * i / max(half, 1)
        r = 1.0
        X.append([r * math.cos(t) + rng.gauss(0, noise),
                  r * math.sin(t) + rng.gauss(0, noise)])
        y.append(0)
    for i in range(n - half):
        t = 2 * math.pi * i / max(n - half, 1)
        r = 0.4
        X.append([r * math.cos(t) + rng.gauss(0, noise),
                  r * math.sin(t) + rng.gauss(0, noise)])
        y.append(1)
    return _shuffle(X, y, rng)


def spiral(n: int = 200, noise: float = 0.15, turns: float = 1.5, seed: int = 0):
    """Two interleaved spiral arms — the classic hard 2-class problem."""
    rng = random.Random(seed)
    X, y = [], []
    half = n // 2
    for cls in (0, 1):
        count = half if cls == 0 else n - half
        for i in range(count):
            frac = i / max(count - 1, 1)
            r = frac
            theta = frac * turns * 2 * math.pi + cls * math.pi
            X.append([r * math.cos(theta) + rng.gauss(0, noise),
                      r * math.sin(theta) + rng.gauss(0, noise)])
            y.append(cls)
    return _shuffle(X, y, rng)


DATASETS = {
    "xor": xor,
    "moons": moons,
    "circles": circles,
    "spiral": spiral,
}


def get(name: str, **kw):
    if name not in DATASETS:
        raise ValueError(f"unknown dataset {name!r}; choose from {sorted(DATASETS)}")
    return DATASETS[name](**kw)


def bounds(X, pad: float = 0.3):
    """Axis-aligned bounding box of X, padded — used for plotting grids."""
    if not X:
        raise ValueError("bounds() needs at least one point")
    xs = [p[0] for p in X]
    ys = [p[1] for p in X]
    return (min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad)
