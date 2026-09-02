import math
import unittest

from beacon.occupancy_grid import OccupancyGrid


class TestOccupancyGrid(unittest.TestCase):
    def test_starts_fully_unknown(self):
        grid = OccupancyGrid(5, 5, 1.0)
        for r in range(grid.rows):
            for c in range(grid.cols):
                self.assertTrue(grid.is_unknown(c, r))
                self.assertFalse(grid.is_free(c, r))
                self.assertFalse(grid.is_occupied(c, r))
                self.assertAlmostEqual(grid.probability(c, r), 0.5)

    def test_single_hit_beam_marks_free_corridor_and_occupied_endpoint(self):
        grid = OccupancyGrid(10, 10, 1.0)
        pose = (0.5, 0.5, 0.0)  # cell (0,0), facing +x
        beams = [(0.0, 5.0)]  # single beam straight ahead, hits at range 5
        grid.integrate_scan(pose, beams, max_range=10.0)

        # A single weak observation shouldn't cross the confident is_free
        # threshold by itself, but it must move every traversed cell
        # toward free (below the 0.5 prior) and the endpoint toward
        # occupied (above it) in the correct, opposite directions.
        for c in range(0, 5):
            self.assertLess(grid.probability(c, 0), 0.5, f"cell {c} should lean free")
        self.assertGreater(grid.probability(5, 0), 0.5)
        # Repeating the same observation should cross the confidence
        # thresholds for both.
        for _ in range(5):
            grid.integrate_scan(pose, beams, max_range=10.0)
        for c in range(0, 5):
            self.assertTrue(grid.is_free(c, 0), f"cell {c} should be free")
        self.assertTrue(grid.is_occupied(5, 0))
        # Nothing beyond the hit was ever observed.
        self.assertTrue(grid.is_unknown(7, 0))

    def test_max_range_miss_clears_free_space_without_marking_occupied(self):
        grid = OccupancyGrid(10, 10, 1.0)
        pose = (0.5, 0.5, 0.0)
        beams = [(0.0, None)]  # no return: dropout or true max-range miss
        for _ in range(6):
            grid.integrate_scan(pose, beams, max_range=8.0)
        for c in range(0, 8):
            self.assertTrue(grid.is_free(c, 0))
        # Crucially: nothing was marked occupied by a miss.
        for r in range(grid.rows):
            for c in range(grid.cols):
                self.assertFalse(grid.is_occupied(c, r))

    def test_repeated_consistent_observations_increase_confidence(self):
        grid = OccupancyGrid(10, 10, 1.0)
        pose = (0.5, 0.5, 0.0)
        p_after = []
        for _ in range(6):
            grid.integrate_scan(pose, [(0.0, 5.0)], max_range=10.0)
            p_after.append(grid.probability(5, 0))
        # Probability of the repeatedly-hit cell should be monotonically
        # non-decreasing as more consistent evidence accumulates, and
        # clamped well short of exactly 1.0.
        for a, b in zip(p_after, p_after[1:]):
            self.assertGreaterEqual(b, a - 1e-9)
        self.assertLess(p_after[-1], 1.0)
        self.assertGreater(p_after[-1], 0.9)

    def test_conflicting_observations_pull_back_toward_uncertain(self):
        grid = OccupancyGrid(10, 10, 1.0)
        pose = (0.5, 0.5, 0.0)
        grid.integrate_scan(pose, [(0.0, 5.0)], max_range=10.0)
        occupied_belief = grid.probability(5, 0)
        self.assertGreater(occupied_belief, 0.5)
        # Now repeatedly observe *through* that same cell as free.
        for _ in range(6):
            grid.integrate_scan(pose, [(0.0, None)], max_range=10.0)
        self.assertLess(grid.probability(5, 0), occupied_belief)

    def test_world_to_cell_and_back_round_trips_to_cell_center(self):
        grid = OccupancyGrid(10, 10, 0.5)
        cell = grid.world_to_cell(3.7, 2.2)
        wx, wy = grid.cell_to_world(*cell)
        back = grid.world_to_cell(wx, wy)
        self.assertEqual(cell, back)

    def test_out_of_bounds_cells_are_safe_and_neutral(self):
        grid = OccupancyGrid(5, 5, 1.0)
        self.assertFalse(grid.in_bounds(-1, 0))
        self.assertFalse(grid.in_bounds(100, 0))
        self.assertAlmostEqual(grid.probability(-1, 0), 0.5)
        self.assertFalse(grid.is_occupied(-1, 0))


if __name__ == "__main__":
    unittest.main()
