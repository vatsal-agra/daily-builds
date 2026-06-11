"""Elevation field: fractal noise shaped into a continent, plus sea level."""

from __future__ import annotations

import math

from .noise import fbm


def generate_elevation(width: int, height: int, seed: int) -> list[float]:
    """Return a flat row-major grid of elevations normalized to [0, 1].

    Combines domain-warped fBm with a soft radial mask so land clusters
    into a continent instead of wrapping noise edge to edge.
    """
    grid = [0.0] * (width * height)
    scale = 3.2 / max(width, height)  # ~3 noise periods across the map
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    max_r = math.hypot(cx, cy)
    for y in range(height):
        for x in range(width):
            nx, ny = x * scale, y * scale
            # Domain warp keeps coastlines from looking blobby.
            wx = nx + 0.9 * (fbm(nx + 11.7, ny + 5.1, seed + 7717, octaves=3) - 0.5)
            wy = ny + 0.9 * (fbm(nx - 3.3, ny + 9.2, seed + 9311, octaves=3) - 0.5)
            e = fbm(wx, wy, seed, octaves=6)
            # Ridged component sharpens mountain chains.
            r = 1.0 - abs(2.0 * fbm(wx * 1.7, wy * 1.7, seed + 4421, octaves=4) - 1.0)
            e = 0.72 * e + 0.28 * r * r
            # Radial falloff: high near center, dipping below sea at edges.
            d = math.hypot(x - cx, y - cy) / max_r
            mask = 1.0 - d * d * 1.35
            grid[y * width + x] = e * 0.65 + 0.35 * mask * e + 0.12 * mask
    lo, hi = min(grid), max(grid)
    span = (hi - lo) or 1.0
    return [(v - lo) / span for v in grid]


def sea_level_for_land_fraction(elevation: list[float], land_fraction: float) -> float:
    """Sea level such that ~land_fraction of cells sit above it."""
    land_fraction = min(max(land_fraction, 0.01), 0.99)
    ordered = sorted(elevation)
    idx = int(len(ordered) * (1.0 - land_fraction))
    idx = min(max(idx, 0), len(ordered) - 1)
    return ordered[idx]
