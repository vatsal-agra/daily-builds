"""Log-odds occupancy grid mapping.

Each cell stores a log-odds value l = log(p / (1-p)) where p is the belief
that the cell is occupied. Log-odds is the standard trick that turns
Bayesian fusion of independent observations into simple addition, and
keeps a straightforward numeric range (no probabilities creeping to 0 or 1
and losing precision).

For every beam in a scan:
  - cells strictly between the sensor and the (noisy) hit point are
    updated as FREE
  - the cell at the hit point (if the beam hit something, i.e. range is
    not None/max-range) is updated as OCCUPIED
  - a beam that returned None (dropout or max-range) still clears free
    space up to max_range, but marks no occupied cell -- there's no
    known obstacle on that bearing, just no return
"""

from __future__ import annotations

import math
from typing import Iterable, List, Optional, Tuple

from .geometry import bresenham_line
from .robot import Pose

Cell = Tuple[int, int]

# log-odds increments for a single free/occupied observation, and clamps
# to keep a handful of confident readings from saturating past what more
# contradicting evidence could ever recover from.
L_FREE = -0.4
L_OCC = 0.85
L_MIN = -6.0
L_MAX = 6.0
L_PRIOR = 0.0  # log-odds of p=0.5, i.e. "unknown"


class OccupancyGrid:
    def __init__(self, width: float, height: float, resolution: float):
        self.resolution = resolution
        self.cols = max(1, int(math.ceil(width / resolution)))
        self.rows = max(1, int(math.ceil(height / resolution)))
        self.log_odds = [L_PRIOR] * (self.cols * self.rows)

    # -- coordinate conversion -------------------------------------------------
    def world_to_cell(self, x: float, y: float) -> Cell:
        c = int(x / self.resolution)
        r = int(y / self.resolution)
        return c, r

    def cell_to_world(self, c: int, r: int) -> Tuple[float, float]:
        return (c + 0.5) * self.resolution, (r + 0.5) * self.resolution

    def in_bounds(self, c: int, r: int) -> bool:
        return 0 <= c < self.cols and 0 <= r < self.rows

    def _idx(self, c: int, r: int) -> int:
        return r * self.cols + c

    # -- queries ----------------------------------------------------------------
    def probability(self, c: int, r: int) -> float:
        if not self.in_bounds(c, r):
            return 0.5
        l = self.log_odds[self._idx(c, r)]
        return 1.0 - 1.0 / (1.0 + math.exp(l))

    def is_occupied(self, c: int, r: int, threshold: float = 0.65) -> bool:
        return self.probability(c, r) >= threshold

    def is_free(self, c: int, r: int, threshold: float = 0.35) -> bool:
        return self.probability(c, r) <= threshold

    def is_unknown(self, c: int, r: int, lo: float = 0.35, hi: float = 0.65) -> bool:
        p = self.probability(c, r)
        return lo < p < hi

    def set_log_odds(self, c: int, r: int, value: float) -> None:
        """Directly set a cell's raw log-odds value, bypassing the usual
        incremental fusion. Used only by metrics.ground_truth_grid() to
        stamp in known-perfect ground truth, never by any estimator."""
        if self.in_bounds(c, r):
            self.log_odds[self._idx(c, r)] = value

    # -- update -------------------------------------------------------------
    def _apply(self, c: int, r: int, delta: float) -> None:
        if not self.in_bounds(c, r):
            return
        i = self._idx(c, r)
        self.log_odds[i] = max(L_MIN, min(L_MAX, self.log_odds[i] + delta))

    def integrate_scan(
        self, pose: Pose, beams: Iterable[Tuple[float, Optional[float]]], max_range: float
    ) -> None:
        x, y, theta = pose
        origin_cell = self.world_to_cell(x, y)
        for off, rng in beams:
            angle = theta + off
            span = rng if rng is not None else max_range
            end_x = x + span * math.cos(angle)
            end_y = y + span * math.sin(angle)
            end_cell = self.world_to_cell(end_x, end_y)
            trace = bresenham_line(origin_cell, end_cell)
            # Every traversed cell up to (but not including) the endpoint is
            # free; the endpoint itself is occupied only for an actual hit.
            for cell in trace[:-1]:
                self._apply(cell[0], cell[1], L_FREE)
            if rng is not None:
                self._apply(trace[-1][0], trace[-1][1], L_OCC)
            else:
                self._apply(trace[-1][0], trace[-1][1], L_FREE)

    # -- inspection / export --------------------------------------------------
    def occupied_cells(self, threshold: float = 0.65) -> List[Cell]:
        out = []
        for r in range(self.rows):
            for c in range(self.cols):
                if self.probability(c, r) >= threshold:
                    out.append((c, r))
        return out

    def to_prob_grid(self) -> List[List[float]]:
        """Row-major list of probabilities, grid[r][c]."""
        return [
            [self.probability(c, r) for c in range(self.cols)] for r in range(self.rows)
        ]

    def to_ascii(self) -> str:
        chars = []
        for r in range(self.rows):
            row = []
            for c in range(self.cols):
                p = self.probability(c, r)
                if p >= 0.65:
                    row.append("#")
                elif p <= 0.35:
                    row.append(".")
                else:
                    row.append(" ")
            chars.append("".join(row))
        return "\n".join(chars)
