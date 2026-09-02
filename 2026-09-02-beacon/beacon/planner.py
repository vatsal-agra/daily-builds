"""A* path planning over a live (possibly still-partial) occupancy grid.

Obstacles are inflated by the robot's radius first, so a path threading
between the returned cells is actually drivable by a robot with physical
extent, not just a zero-radius point. Unknown cells are treated as
impassable by default -- the robot should not plan a "confident" route
through territory it has never actually seen -- with an escape hatch
(`allow_unknown`) used only by the frontier explorer, which by definition
needs to route *to* the boundary of the unknown.
"""

from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Set, Tuple

from .occupancy_grid import OccupancyGrid

Cell = Tuple[int, int]

NEIGHBORS_COST = [
    (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
    (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)),
    (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2)),
]


def compute_blocked(
    grid: OccupancyGrid,
    radius_cells: int,
    allow_unknown: bool = False,
    keep_clear: Optional[Cell] = None,
) -> Set[Cell]:
    blocked: Set[Cell] = set()
    for c, r in grid.occupied_cells():
        for dr in range(-radius_cells, radius_cells + 1):
            for dc in range(-radius_cells, radius_cells + 1):
                if dc * dc + dr * dr <= radius_cells * radius_cells:
                    nc, nr = c + dc, r + dr
                    if grid.in_bounds(nc, nr):
                        blocked.add((nc, nr))
    if not allow_unknown:
        for r in range(grid.rows):
            for c in range(grid.cols):
                if grid.is_unknown(c, r):
                    blocked.add((c, r))
    if keep_clear is not None:
        # The robot is physically standing here right now (it didn't just
        # collide getting here), so however marginal this spot looks under
        # fresh inflation, it must stay escapable -- otherwise a robot that
        # ends a step near a wall could find A* reporting "no path" to
        # anywhere, including a goal only two cells away.
        # Only forgive cells that are blocked purely as *inflation*
        # fallout -- a cell that is itself genuinely occupied stays
        # blocked no matter how close the robot is standing to it, or the
        # planner would happily route the very next hop straight back
        # through the wall the robot is currently wedged against.
        kc, kr = keep_clear
        for dr in range(-radius_cells, radius_cells + 1):
            for dc in range(-radius_cells, radius_cells + 1):
                if dc * dc + dr * dr <= radius_cells * radius_cells:
                    cell = (kc + dc, kr + dr)
                    if not grid.is_occupied(*cell):
                        blocked.discard(cell)
    return blocked


def astar(
    grid: OccupancyGrid,
    start: Cell,
    goal: Cell,
    robot_radius_cells: int,
    allow_unknown: bool = False,
    blocked: Optional[Set[Cell]] = None,
) -> Optional[List[Cell]]:
    if blocked is None:
        blocked = compute_blocked(grid, robot_radius_cells, allow_unknown)

    # A start or goal that itself falls in the inflated-obstacle set is
    # allowed through (the robot may legitimately be close to a wall) but
    # never a cell that's actually out of bounds.
    if not grid.in_bounds(*start) or not grid.in_bounds(*goal):
        return None

    def h(c: Cell) -> float:
        return math.hypot(c[0] - goal[0], c[1] - goal[1])

    open_heap: List[Tuple[float, int, Cell]] = [(h(start), 0, start)]
    came_from: Dict[Cell, Cell] = {}
    g_score: Dict[Cell, float] = {start: 0.0}
    closed: Set[Cell] = set()
    counter = 1

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal:
            return _reconstruct(came_from, current)
        closed.add(current)

        for dc, dr, cost in NEIGHBORS_COST:
            nb = (current[0] + dc, current[1] + dr)
            if not grid.in_bounds(*nb):
                continue
            if nb in blocked and nb != start and nb != goal:
                continue
            tentative = g_score[current] + cost
            if tentative < g_score.get(nb, math.inf):
                g_score[nb] = tentative
                came_from[nb] = current
                heapq.heappush(open_heap, (tentative + h(nb), counter, nb))
                counter += 1

    return None


def _reconstruct(came_from: Dict[Cell, Cell], current: Cell) -> List[Cell]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
