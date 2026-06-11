"""Seeded fractal value noise, no dependencies.

A small integer hash drives lattice values; bilinear interpolation with a
quintic fade gives smooth C2 noise, and fBm stacks octaves for detail.
"""

from __future__ import annotations

_MASK = 0xFFFFFFFF


def _hash2(ix: int, iy: int, seed: int) -> int:
    h = (ix * 374761393 + iy * 668265263 + seed * 2654435761) & _MASK
    h = (h ^ (h >> 13)) * 1274126177 & _MASK
    return (h ^ (h >> 16)) & _MASK


def lattice(ix: int, iy: int, seed: int) -> float:
    """Pseudo-random value in [0, 1) at integer lattice point."""
    return _hash2(ix, iy, seed) / 4294967296.0


def _fade(t: float) -> float:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def value_noise(x: float, y: float, seed: int) -> float:
    """Smooth value noise in [0, 1)."""
    ix, iy = int(x // 1), int(y // 1)
    fx, fy = x - ix, y - iy
    u, v = _fade(fx), _fade(fy)
    a = lattice(ix, iy, seed)
    b = lattice(ix + 1, iy, seed)
    c = lattice(ix, iy + 1, seed)
    d = lattice(ix + 1, iy + 1, seed)
    top = a + (b - a) * u
    bot = c + (d - c) * u
    return top + (bot - top) * v


def fbm(
    x: float,
    y: float,
    seed: int,
    octaves: int = 5,
    lacunarity: float = 2.0,
    gain: float = 0.5,
) -> float:
    """Fractal Brownian motion in [0, 1)."""
    total = 0.0
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for i in range(octaves):
        total += amp * value_noise(x * freq, y * freq, seed + i * 1013)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm
