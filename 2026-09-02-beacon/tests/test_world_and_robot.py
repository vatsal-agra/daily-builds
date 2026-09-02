import math
import random
import unittest

from beacon.robot import MotionNoise, Robot, sample_velocity_motion
from beacon.world import make_maze_world, make_office_world, make_open_world


class TestWorldCollision(unittest.TestCase):
    def setUp(self):
        self.world = make_open_world()

    def test_open_space_no_collision(self):
        self.assertFalse(self.world.collides((2, 2), 0.3))

    def test_outside_boundary_collides(self):
        self.assertTrue(self.world.collides((-1, 5), 0.3))
        self.assertTrue(self.world.collides((self.world.width + 1, 5), 0.3))

    def test_near_boundary_within_radius_collides(self):
        self.assertTrue(self.world.collides((0.1, 5), 0.3))

    def test_near_a_box_obstacle_edge_collides(self):
        # make_open_world places a 2x2 box at (5,5) (spanning x:5-7,
        # y:5-7). Walls are thin segments, not solid-filled volumes --
        # same representation the lidar sees -- so what must collide is
        # a point close to an actual edge, not the box's hollow interior
        # (which a real trajectory could never reach without crossing,
        # and registering a collision against, that edge first).
        self.assertTrue(self.world.collides((5.05, 6.0), 0.1))
        self.assertFalse(self.world.collides((6.0, 6.0), 0.1))

    def test_far_from_everything_is_clear(self):
        self.assertFalse(self.world.collides((10, 19), 0.3))


class TestRaycastAgainstBuiltinMaps(unittest.TestCase):
    def test_office_world_doorway_gap_is_actually_passable(self):
        # office world's vertical wall has a gap from y=8 to y=11 at x=10;
        # a ray fired through the middle of that gap should not be blocked
        # by the wall it's a gap in (it may still hit something farther on).
        world = make_office_world()
        d = world.raycast((5, 9.5), 0.0, max_range=3.0)
        # Nothing should intercept within 3m through the doorway gap.
        self.assertIsNone(d)

    def test_maze_world_border_is_hit(self):
        world = make_maze_world()
        d = world.raycast((1, 1), math.pi, max_range=100.0)
        self.assertIsNotNone(d)
        self.assertAlmostEqual(d, 1.0, places=6)


class TestMotionModel(unittest.TestCase):
    def test_straight_line_zero_noise(self):
        noise = MotionNoise(0, 0, 0, 0, 0, 0)
        rng = random.Random(1)
        pose = (0.0, 0.0, 0.0)
        new_pose = sample_velocity_motion(pose, v=1.0, w=0.0, dt=2.0, noise=noise, rng=rng)
        self.assertAlmostEqual(new_pose[0], 2.0, places=9)
        self.assertAlmostEqual(new_pose[1], 0.0, places=9)
        self.assertAlmostEqual(new_pose[2], 0.0, places=9)

    def test_quarter_circle_zero_noise(self):
        # v=w means the arc radius is 1; driving for pi/2 seconds at
        # w=1 rad/s sweeps a quarter circle. Starting at the origin facing
        # +x, this should end up at (1, 1) facing +y.
        noise = MotionNoise(0, 0, 0, 0, 0, 0)
        rng = random.Random(1)
        pose = (0.0, 0.0, 0.0)
        new_pose = sample_velocity_motion(
            pose, v=1.0, w=1.0, dt=math.pi / 2, noise=noise, rng=rng
        )
        self.assertAlmostEqual(new_pose[0], 1.0, places=6)
        self.assertAlmostEqual(new_pose[1], 1.0, places=6)
        self.assertAlmostEqual(new_pose[2], math.pi / 2, places=6)

    def test_zero_velocity_commanded_produces_zero_variance_motion(self):
        # v=w=0 means every noise term's variance (which scales with v^2
        # and w^2) is exactly zero -- no phantom jitter while "parked".
        noise = MotionNoise(0.05, 0.05, 0.05, 0.05, 0.05, 0.05)
        rng = random.Random(1)
        pose = (3.0, 4.0, 1.0)
        new_pose = sample_velocity_motion(pose, v=0.0, w=0.0, dt=1.0, noise=noise, rng=rng)
        self.assertEqual(new_pose, pose)

    def test_noise_produces_variation_across_samples(self):
        noise = MotionNoise(0.05, 0.05, 0.05, 0.05, 0.02, 0.02)
        rng = random.Random(1)
        pose = (0.0, 0.0, 0.0)
        outcomes = {
            sample_velocity_motion(pose, 1.0, 0.5, 0.5, noise, rng) for _ in range(20)
        }
        self.assertGreater(len(outcomes), 1)


class TestRobotCollisionHandling(unittest.TestCase):
    def test_drive_into_wall_does_not_teleport_through_it(self):
        world = make_open_world()
        # Face directly at the boundary wall, close enough that a full
        # commanded step would tunnel through it if unchecked.
        robot = Robot(
            world, (0.5, 5.0, math.pi), radius=0.3,
            noise=MotionNoise(0, 0, 0, 0, 0, 0), rng=random.Random(2),
        )
        robot.drive(v=5.0, w=0.0, dt=1.0)
        self.assertTrue(robot.collided_last_step)
        # Position must not have crossed the boundary.
        self.assertGreaterEqual(robot.pose[0], 0.0)
        self.assertFalse(world.collides((robot.pose[0], robot.pose[1]), robot.radius))

    def test_drive_in_open_space_moves_and_reports_no_collision(self):
        world = make_open_world()
        robot = Robot(
            world, (10.0, 19.0, 0.0), radius=0.3,
            noise=MotionNoise(0, 0, 0, 0, 0, 0), rng=random.Random(2),
        )
        start = robot.pose
        robot.drive(v=1.0, w=0.0, dt=0.5)
        self.assertFalse(robot.collided_last_step)
        self.assertNotEqual(start, robot.pose)


if __name__ == "__main__":
    unittest.main()
