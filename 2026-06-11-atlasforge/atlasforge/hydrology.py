"""Hydrology: depression filling, flow routing, rivers and lakes.

Uses priority-flood with an epsilon gradient (Barnes et al. 2014) so every
land cell has a strictly descending path to the ocean, then routes flow down
steepest descent, accumulates rainfall, and extracts river polylines from
high-accumulation cells. Cells the flood had to raise become lakes.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

EPSILON = 1e-5
LAKE_DEPTH = 0.004  # filled this far above bedrock => standing water


@dataclass
class Hydrology:
    filled: list[float]
    flow_dir: list[int]            # downstream cell index, -1 for water/pits
    accumulation: list[float]
    lake: list[bool]
    rivers: list[list[int]] = field(default_factory=list)  # cell-index paths


def _neighbors(i: int, width: int, height: int):
    x, y = i % width, i // width
    if x > 0:
        yield i - 1
    if x < width - 1:
        yield i + 1
    if y > 0:
        yield i - width
    if y < height - 1:
        yield i + width
    # Diagonals give rivers more natural courses.
    if x > 0 and y > 0:
        yield i - width - 1
    if x < width - 1 and y > 0:
        yield i - width + 1
    if x > 0 and y < height - 1:
        yield i + width - 1
    if x < width - 1 and y < height - 1:
        yield i + width + 1


def priority_flood(
    width: int, height: int, elevation: list[float], sea_level: float
) -> list[float]:
    """Fill depressions; returns elevations where land drains monotonically."""
    n = width * height
    filled = [0.0] * n
    seen = [False] * n
    heap: list[tuple[float, int, int]] = []
    order = 0
    for i in range(n):
        if elevation[i] <= sea_level:
            seen[i] = True
            filled[i] = elevation[i]
            heap.append((elevation[i], order, i))
            order += 1
    if not heap:  # all-land map: seed from the border cells
        for i in range(n):
            x, y = i % width, i // width
            if x in (0, width - 1) or y in (0, height - 1):
                seen[i] = True
                filled[i] = elevation[i]
                heap.append((elevation[i], order, i))
                order += 1
    heapq.heapify(heap)
    while heap:
        elev, _, i = heapq.heappop(heap)
        for j in _neighbors(i, width, height):
            if seen[j]:
                continue
            seen[j] = True
            filled[j] = max(elevation[j], elev + EPSILON)
            heapq.heappush(heap, (filled[j], order, j))
            order += 1
    return filled


def compute_hydrology(
    width: int,
    height: int,
    elevation: list[float],
    sea_level: float,
    moisture: list[float],
    river_count: int = 24,
    min_river_len: int = 6,
) -> Hydrology:
    n = width * height
    filled = priority_flood(width, height, elevation, sea_level)
    lake = [
        elevation[i] > sea_level and (filled[i] - elevation[i]) > LAKE_DEPTH
        for i in range(n)
    ]

    flow_dir = [-1] * n
    for i in range(n):
        if elevation[i] <= sea_level:
            continue
        best, best_e = -1, filled[i]
        for j in _neighbors(i, width, height):
            if filled[j] < best_e:
                best, best_e = j, filled[j]
        flow_dir[i] = best

    # Accumulate rainfall downstream, visiting cells from high to low.
    accumulation = [0.0] * n
    for i in range(n):
        if elevation[i] > sea_level:
            accumulation[i] = 0.05 + moisture[i]
    for i in sorted(range(n), key=lambda k: filled[k], reverse=True):
        d = flow_dir[i]
        if d >= 0:
            accumulation[d] += accumulation[i]

    # River sources: strongest land cells whose upstream isn't already a
    # river. The threshold tracks the top ~n/60 accumulation cells, so small
    # or single-basin maps legitimately get few (but never dangling) rivers.
    hydro = Hydrology(filled, flow_dir, accumulation, lake)
    land = [i for i in range(n) if elevation[i] > sea_level and not lake[i]]
    if not land:
        return hydro
    candidates = sorted(land, key=lambda i: accumulation[i], reverse=True)
    threshold = accumulation[candidates[min(len(candidates) - 1, max(20, n // 60))]]
    on_river = [False] * n
    sources: list[int] = []
    for i in candidates:
        if accumulation[i] < threshold:
            break
        # A source is a river-grade cell with no river-grade upstream neighbor.
        if any(
            flow_dir[j] == i and accumulation[j] >= threshold
            for j in _neighbors(i, width, height)
        ):
            continue
        sources.append(i)
    for src in sources[: river_count * 3]:
        path = [src]
        cur = src
        while True:
            d = flow_dir[cur]
            if d < 0:
                break
            path.append(d)
            if on_river[d] or elevation[d] <= sea_level or lake[d]:
                break
            cur = d
        if len(path) >= min_river_len:
            for c in path:
                on_river[c] = True
            hydro.rivers.append(path)
        if len(hydro.rivers) >= river_count:
            break
    return hydro
