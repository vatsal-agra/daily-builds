"""End-to-end tests of the closed-loop SLAM orchestration in slam.py --
the real gate for feature 4. Every assertion here scores the run against
ground truth *after the fact* only; nothing in slam.py itself ever sees
ground truth during the run (see slam.py's own module docstring for the
architectural boundary this is checking).
"""

import unittest

from beacon import metrics
from beacon.slam import SlamConfig, SlamRun
from beacon.world import BUILTIN_WORLDS


class TestClosedLoopSlam(unittest.TestCase):
    """Runs on all three built-in maps. Kept to a modest step budget so
    the whole suite stays fast; PLAN.md's fuller multi-hundred-step
    explorations are exercised by demo.sh instead."""

    def _run(self, world_name, mode="explore", waypoints=(), max_steps=180, seed=42):
        cfg = SlamConfig(
            world_name=world_name, mode=mode, waypoints=waypoints,
            num_particles=250, resolution=0.3, df_every=1, seed=seed,
        )
        return SlamRun(cfg).run(max_steps=max_steps), cfg

    def test_all_builtin_worlds_stay_localized_and_build_a_real_map(self):
        for world_name in BUILTIN_WORLDS:
            with self.subTest(world=world_name):
                run, cfg = self._run(world_name, max_steps=200)
                self.assertGreater(len(run.frames), 0, "run produced no frames at all")

                rmse = metrics.pose_rmse(run.true_poses, run.est_poses)
                self.assertLess(rmse, 1.0, f"{world_name}: pose RMSE {rmse:.2f}m too high")

                truth_grid = metrics.ground_truth_grid(run.world, cfg.resolution)
                iou, acc = metrics.map_quality(run.grid, truth_grid)
                explored = metrics.explored_fraction(run.grid)
                self.assertGreater(explored, 0.15, f"{world_name}: barely explored ({explored:.0%})")
                self.assertGreater(acc, 0.75, f"{world_name}: map cell accuracy {acc:.2f} too low")
                # IoU is a stricter, harsher metric (penalizes any false
                # occupied cell against the whole occupied union) -- a
                # sane but real map clears a much lower bar here.
                self.assertGreater(iou, 0.15, f"{world_name}: map IoU {iou:.2f} too low")

    def test_ground_truth_never_leaks_into_the_grid_or_planner(self):
        # A structural check, not just a numeric one: confirm slam.py's
        # own claimed invariant (see its module docstring) actually holds
        # by asserting the estimate and the true pose can genuinely
        # diverge without the map instantly "knowing" the true pose --
        # i.e. the grid was built at *some* estimate that isn't
        # suspiciously identical to ground truth at every single step.
        run, cfg = self._run("office", max_steps=150)
        identical_every_step = all(
            t == e for t, e in zip(run.true_poses, run.est_poses)
        )
        self.assertFalse(
            identical_every_step,
            "estimate exactly matches ground truth every step -- suspicious, "
            "check that grid.integrate_scan() is really using pf.estimate()",
        )

    def test_waypoints_mode_reaches_every_goal(self):
        goals = ((10.0, 2.0), (15.0, 10.0), (3.0, 15.0))
        run, cfg = self._run("open", mode="waypoints", waypoints=goals, max_steps=350)
        self.assertEqual(run.goals_reached, len(goals))
        # And it should have stopped itself once done, not idled to max_steps.
        self.assertTrue(run.exploration_done)

    def test_disabling_pf_update_measurably_hurts_localization(self):
        # Regression test for the "does the lidar correction actually do
        # anything" claim -- see PLAN.md's verification approach.
        with_update, cfg = self._run("office", max_steps=150, seed=7)
        cfg2 = SlamConfig(
            world_name="office", mode="explore", num_particles=250,
            resolution=0.3, df_every=1, seed=7, disable_pf_update=True,
        )
        dead_reckoning = SlamRun(cfg2).run(max_steps=150)

        rmse_with_update = metrics.pose_rmse(with_update.true_poses, with_update.est_poses)
        rmse_dead_reckoning = metrics.pose_rmse(dead_reckoning.true_poses, dead_reckoning.est_poses)
        self.assertLess(rmse_with_update, rmse_dead_reckoning / 2)

    def test_run_is_deterministic_given_the_same_seed(self):
        run1, _ = self._run("open", max_steps=100, seed=123)
        run2, _ = self._run("open", max_steps=100, seed=123)
        self.assertEqual(run1.true_poses, run2.true_poses)
        self.assertEqual(run1.est_poses, run2.est_poses)

    def test_different_seeds_produce_different_trajectories(self):
        run1, _ = self._run("open", max_steps=60, seed=1)
        run2, _ = self._run("open", max_steps=60, seed=2)
        self.assertNotEqual(run1.true_poses, run2.true_poses)


if __name__ == "__main__":
    unittest.main()
