"""Vector math, segment-ray intersection, and grid line tracing.

Everything here is deliberately dependency-free: a robot pose is a plain
(x, y, theta) tuple, a wall is a ((x1, y1), (x2, y2)) segment, and a grid
line trace is a plain list of (col, row) integer pairs.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

Point = Tuple[float, float]
Segment = Tuple[Point, Point]
Cell = Tuple[int, int]


def normalize_angle(angle: float) -> float:
    """Wrap an angle (radians) into (-pi, pi]."""
    a = math.fmod(angle + math.pi, 2 * math.pi)
    if a <= 0:
        a += 2 * math.pi
    return a - math.pi


def ray_segment_intersection(
    origin: Point, direction: Point, seg: Segment
) -> Optional[float]:
    """Distance along `direction` (a unit vector) from `origin` to where the
    ray first crosses segment `seg`, or None if it never does.

    Standard ray/segment intersection solved as a 2x2 linear system:
        origin + t*direction == p1 + u*(p2 - p1),  t >= 0, 0 <= u <= 1
    """
    ox, oy = origin
    dx, dy = direction
    (x1, y1), (x2, y2) = seg
    sx, sy = x2 - x1, y2 - y1

    denom = dx * sy - dy * sx
    if abs(denom) < 1e-12:
        return None  # parallel (or degenerate segment)

    # Solve [dx -sx; dy -sy] * [t; u] = [x1-ox; y1-oy]
    ex, ey = x1 - ox, y1 - oy
    t = (ex * sy - ey * sx) / denom
    u = (ex * dy - ey * dx) / denom

    if t >= 0 and 0.0 <= u <= 1.0:
        return t
    return None


def raycast(
    origin: Point, angle: float, segments: Sequence[Segment], max_range: float
) -> Optional[float]:
    """Nearest intersection distance of a ray (origin, angle) against a list
    of wall segments, capped at max_range. None if nothing is hit."""
    direction = (math.cos(angle), math.sin(angle))
    best: Optional[float] = None
    for seg in segments:
        t = ray_segment_intersection(origin, direction, seg)
        if t is not None and t <= max_range:
            if best is None or t < best:
                best = t
    return best


def bresenham_line(c0: Cell, c1: Cell) -> List[Cell]:
    """Integer grid cells from c0 to c1 inclusive, via Bresenham's algorithm.

    This is the classic mid-point-error formulation: no floating point, no
    skipped cells, symmetric regardless of octant.
    """
    x0, y0 = c0
    x1, y1 = c1
    cells = []

    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy

    x, y = x0, y0
    while True:
        cells.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return cells


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
