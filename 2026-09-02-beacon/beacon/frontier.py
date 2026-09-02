"""Frontier-based autonomous exploration.

A "frontier" cell is a known-free cell that borders at least one
still-unknown cell -- the boundary of what the robot has actually seen.
Driving to the nearest *reachable* frontier, over and over, is the classic
(Yamauchi 1997) exploration policy: no human waypoints, the robot picks
its own next destination purely from what its own map currently looks
like, and stops on its own once there's nothing left to reveal.

"Nearest" is measured the only way that's actually meaningful for a robot
that can't teleport: shortest path distance through the known-free grid,
not straight-line distance -- a frontier cell ten meters away as the crow
flies but three doors down a corridor beats one two meters away on the
far side of a wall. select_frontier_goal runs a single multi-target
Dijkstra expansion from the robot's cell and stops the instant it first
touches *any* frontier cell, which is simultaneously the correct
shortest-path answer and far cheaper than re-running A* once per
candidate frontier.
"""

from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Set, Tuple

from . import planner
from .occupancy_grid import OccupancyGrid

Cell = Tuple[int, int]

_FOUR = [(-1, 0), (1, 0), (0, -1), (0, 1)]
_EIGHT_COST = planner.NEIGHBORS_COST


def find_frontier_cells(grid: OccupancyGrid) -> List[Cell]:
    frontiers = []
    for r in range(grid.rows):
        for c in range(grid.cols):
            if not grid.is_free(c, r):
                continue
            for dc, dr in _FOUR:
                nc, nr = c + dc, r + dr
                if grid.in_bounds(nc, nr) and grid.is_unknown(nc, nr):
                    frontiers.append((c, r))
                    break
    return frontiers


def select_frontier_goal(
    grid: OccupancyGrid,
    from_cell: Cell,
    robot_radius_cells: int,
    avoid: Optional[Set[Cell]] = None,
) -> Optional[Tuple[Cell, List[Cell]]]:
    """Returns (goal_cell, path) for the *path-distance*-nearest frontier
    cell reachable from from_cell, or None if there is nothing left to
    explore (no frontiers) or nothing reachable remains (e.g. every
    frontier sits behind a gap narrower than the robot)."""
    frontier_set = set(find_frontier_cells(grid))
    if avoid:
        frontier_set -= avoid
    # The robot's own cell is never a valid destination, even if it
    # currently qualifies as a frontier: a scan was already taken from
    # right here, so if an adjacent cell is still unknown after that, it's
    # in a shadow this pose can never resolve (behind an obstacle, most
    # likely) -- driving "to" the cell it's already standing on would be a
    # zero-length path that changes nothing and gets proposed again next
    # step, forever. The unknown neighbor needs to be seen from somewhere
    # else, so it must search past this cell for a genuinely different one.
    frontier_set.discard(from_cell)
    if not frontier_set:
        return None

    blocked = planner.compute_blocked(
        grid, robot_radius_cells, allow_unknown=False, keep_clear=from_cell
    )

    came_from: Dict[Cell, Cell] = {}
    g_score: Dict[Cell, float] = {from_cell: 0.0}
    heap: List[Tuple[float, int, Cell]] = [(0.0, 0, from_cell)]
    closed: Set[Cell] = set()
    counter = 1

    while heap:
        d, _, cur = heapq.heappop(heap)
        if cur in closed:
            continue
        closed.add(cur)
        if cur in frontier_set:
            return cur, _reconstruct(came_from, cur)

        for dc, dr, cost in _EIGHT_COST:
            nb = (cur[0] + dc, cur[1] + dr)
            if not grid.in_bounds(*nb) or nb in closed:
                continue
            if nb in blocked and nb != from_cell:
                continue
            nd = d + cost
            if nd < g_score.get(nb, math.inf):
                g_score[nb] = nd
                came_from[nb] = cur
                heapq.heappush(heap, (nd, counter, nb))
                counter += 1

    return None


def _reconstruct(came_from: Dict[Cell, Cell], current: Cell) -> List[Cell]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
