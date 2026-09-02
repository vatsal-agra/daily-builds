import math
import unittest
from collections import deque

from beacon import planner
from beacon.occupancy_grid import OccupancyGrid


def _make_grid_with_free_rect(cols, rows, resolution=1.0):
    """A grid where every cell has been observed free (so is_unknown never
    blocks the planner) except whatever the test marks occupied."""
    grid = OccupancyGrid(cols * resolution, rows * resolution, resolution)
    for r in range(grid.rows):
        for c in range(grid.cols):
            grid.set_log_odds(c, r, -6.0)  # confidently free
    return grid


def _bfs_reference_path_length(grid, start, goal, blocked):
    """Unweighted 4-connected BFS oracle, used only to sanity-check that
    A* finds a path exactly when one actually exists (not to check the
    diagonal-weighted cost, which BFS doesn't model)."""
    if start in blocked or goal in blocked:
        return None
    q = deque([start])
    seen = {start}
    while q:
        cur = q.popleft()
        if cur == goal:
            return True
        for dc, dr in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nb = (cur[0] + dc, cur[1] + dr)
            if not grid.in_bounds(*nb) or nb in seen or nb in blocked:
                continue
            seen.add(nb)
            q.append(nb)
    return None


class TestAstar(unittest.TestCase):
    def test_start_equals_goal(self):
        grid = _make_grid_with_free_rect(10, 10)
        path = planner.astar(grid, (3, 3), (3, 3), robot_radius_cells=1)
        self.assertEqual(path, [(3, 3)])

    def test_straight_line_open_grid(self):
        grid = _make_grid_with_free_rect(10, 10)
        path = planner.astar(grid, (0, 0), (5, 0), robot_radius_cells=0)
        self.assertIsNotNone(path)
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], (5, 0))
        # Straight open corridor: should take the direct route, 6 cells.
        self.assertEqual(len(path), 6)

    def test_diagonal_move_is_shorter_than_a_stairstep(self):
        grid = _make_grid_with_free_rect(10, 10)
        path = planner.astar(grid, (0, 0), (5, 5), robot_radius_cells=0)
        self.assertIsNotNone(path)
        # A pure-diagonal path exists and A* must find it (6 cells, not 11).
        self.assertEqual(len(path), 6)

    def test_wall_forces_a_detour(self):
        grid = _make_grid_with_free_rect(10, 10)
        # A vertical wall spanning the whole grid except one gap at row 8.
        for r in range(10):
            if r != 8:
                grid.set_log_odds(5, r, 6.0)  # confidently occupied
        path = planner.astar(grid, (0, 0), (9, 0), robot_radius_cells=0)
        self.assertIsNotNone(path)
        cells = set(path)
        self.assertIn((5, 8), cells)  # must funnel through the one gap
        for r in range(10):
            if r != 8:
                self.assertNotIn((5, r), cells)

    def test_fully_enclosed_goal_is_unreachable(self):
        grid = _make_grid_with_free_rect(10, 10)
        gx, gy = 5, 5
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if (dc, dr) != (0, 0):
                    grid.set_log_odds(gx + dc, gy + dr, 6.0)
        path = planner.astar(grid, (0, 0), (gx, gy), robot_radius_cells=0)
        self.assertIsNone(path)

    def test_matches_bfs_reachability_on_random_obstacle_field(self):
        import random

        rng = random.Random(7)
        grid = _make_grid_with_free_rect(15, 15)
        blocked_truth = set()
        for _ in range(40):
            c, r = rng.randrange(15), rng.randrange(15)
            if (c, r) not in ((0, 0), (14, 14)):
                grid.set_log_odds(c, r, 6.0)
                blocked_truth.add((c, r))

        computed_blocked = planner.compute_blocked(grid, radius_cells=0)
        path = planner.astar(grid, (0, 0), (14, 14), robot_radius_cells=0)
        reachable = _bfs_reference_path_length(grid, (0, 0), (14, 14), computed_blocked)
        self.assertEqual(path is not None, bool(reachable))

    def test_robot_radius_inflation_blocks_a_too_narrow_gap(self):
        grid = _make_grid_with_free_rect(10, 10)
        for r in range(10):
            if r != 5:
                grid.set_log_odds(5, r, 6.0)
        # With zero inflation the single-cell gap at row 5 is passable.
        self.assertIsNotNone(planner.astar(grid, (0, 5), (9, 5), robot_radius_cells=0))
        # Inflating by 1 cell closes a 1-cell-wide gap between two walls
        # that are otherwise fully blocked -- only the passage itself was
        # open, so any inflation should seal it.
        blocked = planner.compute_blocked(grid, radius_cells=1)
        self.assertIn((5, 5), blocked)


class TestComputeBlocked(unittest.TestCase):
    def test_unknown_cells_blocked_unless_allowed(self):
        grid = OccupancyGrid(5, 5, 1.0)  # everything starts unknown
        blocked = planner.compute_blocked(grid, radius_cells=0, allow_unknown=False)
        self.assertEqual(len(blocked), grid.cols * grid.rows)
        blocked_allowed = planner.compute_blocked(grid, radius_cells=0, allow_unknown=True)
        self.assertEqual(len(blocked_allowed), 0)

    def test_keep_clear_does_not_unblock_genuinely_occupied_cells(self):
        grid = _make_grid_with_free_rect(5, 5)
        grid.set_log_odds(2, 2, 6.0)  # the robot's own cell is a real wall (contrived)
        blocked = planner.compute_blocked(
            grid, radius_cells=1, allow_unknown=False, keep_clear=(2, 2)
        )
        self.assertIn((2, 2), blocked)

    def test_keep_clear_unblocks_pure_inflation_fallout_near_robot(self):
        grid = _make_grid_with_free_rect(5, 5)
        grid.set_log_odds(2, 3, 6.0)  # a wall one cell away from the robot
        without = planner.compute_blocked(grid, radius_cells=1, allow_unknown=False)
        self.assertIn((2, 2), without)  # inflated into the robot's own cell
        with_keep_clear = planner.compute_blocked(
            grid, radius_cells=1, allow_unknown=False, keep_clear=(2, 2)
        )
        self.assertNotIn((2, 2), with_keep_clear)


if __name__ == "__main__":
    unittest.main()
