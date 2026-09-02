"""Multi-source BFS distance transform: for every cell, the (grid-step)
distance to the nearest currently-occupied cell.

This powers the likelihood-field observation model (Probabilistic
Robotics, section 6.4): instead of ray-casting every particle against
every beam every step (expensive, and brittle when the live map still has
gaps), each beam endpoint is simply looked up in this precomputed field --
O(1) per beam. It's recomputed periodically as the occupancy grid changes,
not every single step, since it's the one genuinely global operation in
the pipeline.
"""

from __future__ import annotations

from collections import deque
from typing import List, Tuple

from .occupancy_grid import OccupancyGrid

Cell = Tuple[int, int]

# 8-connected neighborhood with Euclidean step costs, so the BFS distance
# is a decent approximation of true Euclidean distance rather than taxicab.
_NEIGHBORS = [
    (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
    (-1, -1, 1.4142135623730951), (-1, 1, 1.4142135623730951),
    (1, -1, 1.4142135623730951), (1, 1, 1.4142135623730951),
]


class DistanceField:
    """dist[r][c] * resolution == approximate world-frame distance (meters)
    from cell (c, r) to the nearest occupied cell known so far."""

    def __init__(self, grid: OccupancyGrid, threshold: float = 0.65, max_dist_cells: float = 25.0):
        self.grid = grid
        self.cols = grid.cols
        self.rows = grid.rows
        self.max_dist_cells = max_dist_cells
        self.dist = self._compute(threshold)

    def _compute(self, threshold: float) -> List[float]:
        n = self.cols * self.rows
        dist = [self.max_dist_cells] * n
        dq: deque = deque()
        for r in range(self.rows):
            for c in range(self.cols):
                if self.grid.probability(c, r) >= threshold:
                    idx = r * self.cols + c
                    dist[idx] = 0.0
                    dq.append((c, r))

        # Dijkstra-like multi-source relaxation via a plain BFS deque is not
        # exact for weighted edges, so use a small priority queue instead --
        # cell counts here are small enough (~1e4) that this stays fast.
        import heapq

        heap = [(0.0, c, r) for (c, r) in dq]
        heapq.heapify(heap)
        visited = bytearray(n)
        while heap:
            d, c, r = heapq.heappop(heap)
            idx = r * self.cols + c
            if visited[idx]:
                continue
            visited[idx] = 1
            for dc, dr, cost in _NEIGHBORS:
                nc, nr = c + dc, r + dr
                if 0 <= nc < self.cols and 0 <= nr < self.rows:
                    nidx = nr * self.cols + nc
                    nd = d + cost
                    if nd < dist[nidx]:
                        dist[nidx] = nd
                        heapq.heappush(heap, (nd, nc, nr))
        return dist

    def distance_cells(self, c: int, r: int) -> float:
        if 0 <= c < self.cols and 0 <= r < self.rows:
            return self.dist[r * self.cols + c]
        return self.max_dist_cells

    def distance_world(self, x: float, y: float) -> float:
        c, r = self.grid.world_to_cell(x, y)
        return self.distance_cells(c, r) * self.grid.resolution
