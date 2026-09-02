import unittest

from beacon import metrics
from beacon.occupancy_grid import OccupancyGrid
from beacon.world import make_open_world


class TestPoseMetrics(unittest.TestCase):
    def test_rmse_zero_for_identical_poses(self):
        poses = [(1.0, 2.0, 0.0), (3.0, 4.0, 1.0)]
        self.assertAlmostEqual(metrics.pose_rmse(poses, poses), 0.0)

    def test_rmse_matches_hand_computation(self):
        true_poses = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0)]
        est_poses = [(3.0, 4.0, 0.0), (0.0, 0.0, 0.0)]
        # errors: 5.0 and 0.0 -> rmse = sqrt((25+0)/2) = sqrt(12.5)
        self.assertAlmostEqual(metrics.pose_rmse(true_poses, est_poses), 12.5 ** 0.5)

    def test_final_pose_error_ignores_heading(self):
        self.assertAlmostEqual(
            metrics.final_pose_error((0, 0, 0.0), (3, 4, 99.0)), 5.0
        )


class TestGroundTruthGrid(unittest.TestCase):
    def test_rasterizes_a_wall_as_occupied_and_interior_as_free(self):
        world = make_open_world()
        resolution = 0.1
        grid = metrics.ground_truth_grid(world, resolution=resolution, wall_thickness=0.15)
        # The cell whose center sits right on the boundary wall (x=0)
        # should be occupied.
        c, r = grid.world_to_cell(0.0, 5.0)
        self.assertTrue(grid.is_occupied(c, r))
        # A cell in genuinely open interior space should be free.
        c2, r2 = grid.world_to_cell(10.0, 19.0)
        self.assertTrue(grid.is_free(c2, r2))


class TestMapQuality(unittest.TestCase):
    def test_perfect_match_gives_iou_one(self):
        truth = OccupancyGrid(5, 5, 1.0)
        for r in range(5):
            for c in range(5):
                truth.set_log_odds(c, r, 6.0 if c == 2 else -6.0)
        est = OccupancyGrid(5, 5, 1.0)
        for r in range(5):
            for c in range(5):
                est.set_log_odds(c, r, 6.0 if c == 2 else -6.0)
        iou, acc = metrics.map_quality(est, truth)
        self.assertAlmostEqual(iou, 1.0)
        self.assertAlmostEqual(acc, 1.0)

    def test_completely_wrong_map_gives_iou_zero(self):
        truth = OccupancyGrid(4, 4, 1.0)
        est = OccupancyGrid(4, 4, 1.0)
        for r in range(4):
            for c in range(4):
                truth.set_log_odds(c, r, 6.0 if c == 0 else -6.0)
                est.set_log_odds(c, r, 6.0 if c == 3 else -6.0)
        iou, acc = metrics.map_quality(est, truth)
        self.assertAlmostEqual(iou, 0.0)

    def test_unknown_cells_excluded_from_scoring(self):
        truth = OccupancyGrid(3, 3, 1.0)
        est = OccupancyGrid(3, 3, 1.0)
        for r in range(3):
            for c in range(3):
                truth.set_log_odds(c, r, 6.0 if (c, r) == (1, 1) else -6.0)
        # est knows nothing at all -- every cell stays unknown.
        iou, acc = metrics.map_quality(est, truth)
        self.assertEqual(acc, 0.0)  # total explored cells = 0

    def test_explored_fraction(self):
        grid = OccupancyGrid(4, 4, 1.0)  # 16 cells, all unknown
        self.assertAlmostEqual(metrics.explored_fraction(grid), 0.0)
        for c in range(4):
            grid.set_log_odds(c, 0, -6.0)  # 4 of 16 cells now known
        self.assertAlmostEqual(metrics.explored_fraction(grid), 4 / 16)


if __name__ == "__main__":
    unittest.main()
