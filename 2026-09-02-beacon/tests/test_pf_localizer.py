"""Tests the particle filter in isolation against a *known* map (fed in
via metrics.ground_truth_grid, a legitimate test-only use of ground
truth -- the point here is to test localization quality independent of
mapping quality, which the full closed-loop SLAM tests can't isolate).
"""

import math
import random
import unittest

from beacon import metrics
from beacon.distance_field import DistanceField
from beacon.lidar import LidarSpec, scan as lidar_scan
from beacon.pf_localizer import ObservationModel, ParticleFilter
from beacon.robot import MotionNoise, Robot
from beacon.world import make_open_world


def _run_tracking(rng_seed, init_std, kidnap_at=None, kidnap_offset=(0.0, 0.0), steps=260):
    world = make_open_world()
    truth_grid = metrics.ground_truth_grid(world, 0.3)
    dfield = DistanceField(truth_grid, threshold=0.65)

    true_pose = (2.0, 2.0, 0.0)
    robot = Robot(
        world, true_pose, radius=0.3,
        noise=MotionNoise(0.01, 0.01, 0.01, 0.01, 0.0, 0.0),
        rng=random.Random(rng_seed + 1),
    )
    pf = ParticleFilter(
        400, true_pose, init_std=init_std,
        motion_noise=MotionNoise(0.05, 0.05, 0.05, 0.05, 0.01, 0.01),
        obs_model=ObservationModel(),
        rng=random.Random(rng_seed + 2),
    )
    lidar_spec = LidarSpec()
    scan_rng = random.Random(rng_seed + 3)

    errors = []
    for i in range(steps):
        v = 0.7
        w = 0.6 * math.sin(i * 0.05)  # gentle wander, avoids repeating the same view
        robot.drive(v, w, 0.2)
        beams = lidar_scan(world, robot.pose, lidar_spec, scan_rng)
        v_for_pf = 0.0 if robot.collided_last_step else v
        pf.predict(v_for_pf, w, 0.2)
        pf.update(beams, dfield, lidar_spec.max_range)

        if kidnap_at is not None and i == kidnap_at:
            for p in pf.particles:
                p[0] += kidnap_offset[0]
                p[1] += kidnap_offset[1]

        est = pf.estimate()
        errors.append(math.hypot(robot.pose[0] - est[0], robot.pose[1] - est[1]))
    return errors


class TestParticleFilterConvergence(unittest.TestCase):
    def test_converges_from_realistic_initial_uncertainty(self):
        # ~0.6m position, ~30 degree heading uncertainty: the standard MCL
        # pose-tracking setup (roughly-known start), not global/kidnapped-
        # robot localization.
        errors = _run_tracking(rng_seed=100, init_std=(0.6, 0.6, 0.5), steps=200)
        mean_late = sum(errors[150:200]) / 50
        self.assertLess(mean_late, 0.2, f"mean late-run error {mean_late:.3f}m too high")

    def test_recovers_from_injected_drift(self):
        errors = _run_tracking(
            rng_seed=101, init_std=(0.4, 0.4, 0.3),
            kidnap_at=150, kidnap_offset=(1.0, -0.8), steps=260,
        )
        pre_kidnap = sum(errors[100:150]) / 50
        right_after = errors[150]
        recovered = sum(errors[230:260]) / 30
        self.assertLess(pre_kidnap, 0.2)
        self.assertGreater(right_after, pre_kidnap, "kidnap should visibly spike the error")
        self.assertLess(recovered, 0.25, f"failed to recover, late error {recovered:.3f}m")

    def test_particle_filter_beats_dead_reckoning(self):
        # The whole point of the lidar correction: with it disabled
        # (pure odometry integration), error must end up substantially
        # worse over the same trajectory and noise.
        tracked = _run_tracking(rng_seed=55, init_std=(0.3, 0.3, 0.2), steps=200)

        # Dead-reckoning baseline: same world/robot/noise, but the filter
        # never calls update() -- particles only ever predict.
        world = make_open_world()
        true_pose = (2.0, 2.0, 0.0)
        robot = Robot(
            world, true_pose, radius=0.3,
            noise=MotionNoise(0.01, 0.01, 0.01, 0.01, 0.0, 0.0),
            rng=random.Random(56),
        )
        pf = ParticleFilter(
            400, true_pose, init_std=(0.3, 0.3, 0.2),
            motion_noise=MotionNoise(0.05, 0.05, 0.05, 0.05, 0.01, 0.01),
            obs_model=ObservationModel(), rng=random.Random(57),
        )
        dead_reckoning_errors = []
        for i in range(200):
            v, w = 0.7, 0.6 * math.sin(i * 0.05)
            robot.drive(v, w, 0.2)
            v_for_pf = 0.0 if robot.collided_last_step else v
            pf.predict(v_for_pf, w, 0.2)  # no update() call at all
            est = pf.estimate()
            dead_reckoning_errors.append(math.hypot(robot.pose[0] - est[0], robot.pose[1] - est[1]))

        tracked_final = sum(tracked[-30:]) / 30
        dead_reckoning_final = sum(dead_reckoning_errors[-30:]) / 30
        self.assertLess(tracked_final, dead_reckoning_final / 2)


if __name__ == "__main__":
    unittest.main()
