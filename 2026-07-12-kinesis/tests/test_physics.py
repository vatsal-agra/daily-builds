import math
import random
import unittest

from kinesis import vecmath as vm
from kinesis.genome import Genome
from kinesis.physics import RigidBody, RevoluteJoint, World, MAX_LINEAR_CORRECTION


class TestFreeFall(unittest.TestCase):
    def test_matches_analytic_kinematics(self):
        b = RigidBody(mass=2.0, inertia=1.0, half_length=0.1, half_width=0.1,
                       pos=(0.0, 100.0), angle=0.0)
        world = World([b], [], ground_y=-1000.0)
        dt = 1 / 240
        for _ in range(240):
            world.step(dt)
        g = 9.81
        # semi-implicit Euler has a small, bounded, well-understood bias vs analytic
        self.assertAlmostEqual(b.pos[1], 100.0 - 0.5 * g * 1.0 ** 2, delta=0.05)
        self.assertAlmostEqual(b.vel[1], -g * 1.0, places=6)


class TestPendulum(unittest.TestCase):
    def test_period_matches_physical_pendulum_formula(self):
        L, mass = 2.0, 3.0
        inertia = mass * L * L / 12.0
        static = RigidBody(mass=0, inertia=0, half_length=0.01, half_width=0.01,
                            pos=(0.0, 10.0), angle=0.0)
        angle0 = -math.pi / 2 + 0.05
        hl = L / 2.0
        rod = RigidBody(mass=mass, inertia=inertia, half_length=hl, half_width=0.05,
                         pos=(0, 0), angle=angle0)
        anchor_local_rod = (-hl, 0.0)
        rod.pos = vm.sub(static.pos, vm.rotate(anchor_local_rod, angle0))
        joint = RevoluteJoint(static, rod, (0.0, 0.0), anchor_local_rod, angle0,
                               limit_span=10.0, max_motor_torque=0.0)
        world = World([static, rod], [joint], ground_y=-1000.0)

        dt = 1 / 960
        eq = -math.pi / 2
        prev_dev = rod.angle - eq
        crossing_times = []
        t = 0.0
        for _ in range(int(20 / dt)):
            world.step(dt)
            t += dt
            dev = rod.angle - eq
            if prev_dev < 0 <= dev:
                crossing_times.append(t)
            prev_dev = dev

        periods = [crossing_times[i + 1] - crossing_times[i] for i in range(len(crossing_times) - 1)]
        measured = sum(periods) / len(periods)
        analytic = 2 * math.pi * math.sqrt(2 * L / (3 * 9.81))
        self.assertAlmostEqual(measured, analytic, delta=0.01)


class TestGroundContact(unittest.TestCase):
    def test_box_settles_flat_with_near_zero_penetration(self):
        b = RigidBody(mass=5.0, inertia=1.0, half_length=0.3, half_width=0.15,
                       pos=(0, 1.0), angle=0.1)
        world = World([b], [], ground_y=0.0)
        dt = 1 / 240
        for _ in range(600):
            world.step(dt)
        lowest = min(c[1] for c in b.corners())
        self.assertGreater(lowest, -0.01)
        self.assertLess(abs(b.angle), 0.01)
        self.assertLess(vm.length(b.vel), 0.01)
        self.assertLess(abs(b.ang_vel), 0.01)


class TestMotorAndLimit(unittest.TestCase):
    def _single_joint_world(self, limit_span=0.6, max_motor_torque=50.0):
        static = RigidBody(mass=0, inertia=0, half_length=0.01, half_width=0.01,
                            pos=(0.0, 5.0), angle=0.0)
        hl = 0.5
        rod = RigidBody(mass=1.0, inertia=1.0 / 12.0, half_length=hl, half_width=0.05,
                         pos=(0, 0), angle=0.0)
        anchor_local_rod = (-hl, 0.0)
        rod.pos = vm.sub(static.pos, vm.rotate(anchor_local_rod, 0.0))
        joint = RevoluteJoint(static, rod, (0, 0), anchor_local_rod, rest_angle=0.0,
                               limit_span=limit_span, max_motor_torque=max_motor_torque,
                               servo_kp=80.0)
        world = World([static, rod], [joint], ground_y=-1000.0)
        return world, rod, joint

    def test_motor_tracks_target_within_limit(self):
        world, rod, joint = self._single_joint_world()
        joint.target_angle = 0.5
        for _ in range(480):
            world.step(1 / 240)
        self.assertAlmostEqual(rod.angle, 0.5, delta=0.01)

    def test_limit_clamps_overshoot(self):
        world, rod, joint = self._single_joint_world()
        joint.target_angle = 5.0  # far beyond limit_span=0.6
        for _ in range(960):
            world.step(1 / 240)
        # A hard, unreachable target keeps commanding max torque against
        # the limit forever, so the soft (Baumgarte) limit constraint
        # settles at a small steady-state overshoot rather than exactly
        # limit_span -- bound it generously rather than to an exact value.
        self.assertLess(rod.angle, 0.65)
        self.assertGreater(rod.angle, 0.55)


class TestNoExplosiveCorrections(unittest.TestCase):
    """Regression test for the Baumgarte-bias explosion found during
    adversarial review: a random population of creatures should never
    reach cartoonish speeds/spins from constraint correction alone."""

    def test_random_genomes_stay_within_sane_kinematic_bounds(self):
        from kinesis.simulate import run_simulation
        rng = random.Random(123)
        worst_speed = 0.0
        worst_spin = 0.0
        for _ in range(8):
            g = Genome.random(rng)
            r = run_simulation(g, duration=2.5, record_trace=True)
            if len(r.trace) < 2:
                continue
            xs = [f[0][0] for _, f in r.trace]
            ys = [f[0][1] for _, f in r.trace]
            angs = [f[0][2] for _, f in r.trace]
            max_dx = max(abs(xs[i + 1] - xs[i]) for i in range(len(xs) - 1)) * 60
            max_dy = max(abs(ys[i + 1] - ys[i]) for i in range(len(ys) - 1)) * 60
            spin = max(angs) - min(angs)
            worst_speed = max(worst_speed, max_dx, max_dy)
            worst_spin = max(worst_spin, spin)
        # generous bounds -- real bug produced 28 m/s / 26 rad; a sane
        # creature tumbling once should stay well under these
        self.assertLess(worst_speed, 20.0)
        self.assertLess(worst_spin, 15.0)

    def test_max_linear_correction_constant_is_finite_and_small(self):
        self.assertGreater(MAX_LINEAR_CORRECTION, 0)
        self.assertLess(MAX_LINEAR_CORRECTION, 1.0)


if __name__ == "__main__":
    unittest.main()
