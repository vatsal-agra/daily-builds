import unittest

from beacon import frontier
from beacon.occupancy_grid import OccupancyGrid


def _grid_from_ascii(rows, resolution=1.0):
    """Build a grid from a list of equal-length strings:
    '.' = free, '#' = occupied, ' ' = unknown. Row 0 is the top row (r=0)."""
    height = len(rows)
    width = len(rows[0])
    grid = OccupancyGrid(width * resolution, height * resolution, resolution)
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == ".":
                grid.set_log_odds(c, r, -6.0)
            elif ch == "#":
                grid.set_log_odds(c, r, 6.0)
            # ' ' left at the prior (unknown)
    return grid


class TestFindFrontierCells(unittest.TestCase):
    def test_free_cell_next_to_unknown_is_a_frontier(self):
        grid = _grid_from_ascii([
            "..#",
            "..#",
            "###",
        ])
        # Every free cell here actually borders another free cell only --
        # replace one with a real free/unknown boundary case explicitly.
        grid2 = _grid_from_ascii([
            "...",
            "...",
            "   ",
        ])
        frontiers = frontier.find_frontier_cells(grid2)
        # The bottom row of the free block (r=1) borders unknown (r=2).
        self.assertIn((0, 1), frontiers)
        self.assertIn((1, 1), frontiers)
        self.assertIn((2, 1), frontiers)
        # The top row (r=0) does not border anything unknown.
        self.assertNotIn((0, 0), frontiers)

    def test_no_frontiers_when_fully_known(self):
        grid = _grid_from_ascii([
            "...",
            "...",
            "###",
        ])
        self.assertEqual(frontier.find_frontier_cells(grid), [])

    def test_occupied_cells_are_never_frontiers(self):
        grid = _grid_from_ascii([
            "#  ",
        ])
        self.assertEqual(frontier.find_frontier_cells(grid), [])


class TestSelectFrontierGoal(unittest.TestCase):
    def test_returns_none_when_no_frontiers(self):
        grid = _grid_from_ascii(["...", "...", "..."])
        self.assertIsNone(frontier.select_frontier_goal(grid, (0, 0), robot_radius_cells=0))

    def test_prefers_reachable_frontier_over_a_closer_unreachable_one(self):
        # Columns 2-5 in rows 0-2 form a free "island" with its own
        # frontier that's close in a straight line to (0,0) -- but it's
        # walled off with *no* gap anywhere (column 1 solid in rows 0-3,
        # row 3 solid across), so it's genuinely unreachable, not just a
        # long detour. Column 0 stays open all the way down to a real,
        # farther-away (in straight-line terms) frontier at (0,4).
        rows = [
            ".#    ",  # r0
            ".#....",  # r1
            ".#....",  # r2
            ".#####",  # r3: only column 0 stays open
            ".     ",  # r4: column 0 free, rest unknown -- reachable frontier
        ]
        grid = _grid_from_ascii(rows)
        result = frontier.select_frontier_goal(grid, (0, 0), robot_radius_cells=0)
        self.assertIsNotNone(result)
        goal, path = result
        # The island frontier (e.g. (2,1)) is closer as the crow flies
        # but must never be selected -- it's unreachable outright.
        self.assertNotIn(goal, [(2, 0), (2, 1), (2, 2), (3, 1), (4, 1), (5, 1)])
        self.assertEqual(goal, (0, 4))
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], goal)
        for (c0, r0), (c1, r1) in zip(path, path[1:]):
            self.assertLessEqual(max(abs(c1 - c0), abs(r1 - r0)), 1)

    def test_own_cell_as_frontier_is_excluded_and_search_continues(self):
        # Regression test for the infinite-self-stall bug found in
        # adversarial review: if the robot's own cell qualifies as a
        # frontier, it must never be returned as its own goal.
        grid = OccupancyGrid(3, 3, 1.0)
        grid.set_log_odds(0, 0, -6.0)  # only the robot's own cell is known-free
        result = frontier.select_frontier_goal(grid, (0, 0), robot_radius_cells=0)
        if result is not None:
            goal, _ = result
            self.assertNotEqual(goal, (0, 0))

    def test_avoid_set_excludes_blacklisted_cells(self):
        grid = _grid_from_ascii(["....", "....", "    "])
        first = frontier.select_frontier_goal(grid, (0, 0), robot_radius_cells=0)
        self.assertIsNotNone(first)
        goal, _ = first
        second = frontier.select_frontier_goal(
            grid, (0, 0), robot_radius_cells=0, avoid={goal}
        )
        if second is not None:
            self.assertNotEqual(second[0], goal)


if __name__ == "__main__":
    unittest.main()
