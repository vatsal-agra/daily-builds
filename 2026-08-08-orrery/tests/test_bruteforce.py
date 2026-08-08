import random
import unittest

from orrery.vector import Vec3
from orrery.body import Body
from orrery import bruteforce


class TestBruteforce(unittest.TestCase):
    def test_empty_bodies(self):
        self.assertEqual(bruteforce.compute_accelerations([], G=1.0), [])

    def test_single_body_no_force(self):
        b = [Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0))]
        accel = bruteforce.compute_accelerations(b, G=1.0)
        self.assertEqual(accel, [Vec3(0, 0, 0)])

    def test_two_body_newtons_third_law(self):
        b = [
            Body("a", 2.0, Vec3(0, 0, 0), Vec3(0, 0, 0)),
            Body("b", 3.0, Vec3(4, 0, 0), Vec3(0, 0, 0)),
        ]
        accel = bruteforce.compute_accelerations(b, G=1.0)
        # F_i = m_i * a_i must be equal and opposite to F_j = m_j * a_j.
        f_a = accel[0] * b[0].mass
        f_b = accel[1] * b[1].mass
        self.assertAlmostEqual((f_a + f_b).norm(), 0.0, places=12)
        # Attractive: a on body 'a' points toward body 'b' (+x).
        self.assertGreater(accel[0].x, 0)
        self.assertLess(accel[1].x, 0)

    def test_known_magnitude(self):
        b = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)),
            Body("b", 1.0, Vec3(2, 0, 0), Vec3(0, 0, 0)),
        ]
        accel = bruteforce.compute_accelerations(b, G=1.0)
        # a = G*m/r^2 = 1*1/4 = 0.25
        self.assertAlmostEqual(accel[0].norm(), 0.25, places=12)

    def test_dead_bodies_excluded(self):
        b = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)),
            Body("b", 1.0, Vec3(1, 0, 0), Vec3(0, 0, 0)),
        ]
        b[1].alive = False
        accel = bruteforce.compute_accelerations(b, G=1.0)
        self.assertEqual(accel[0], Vec3(0, 0, 0))

    def test_coincident_positions_softening_zero_no_crash(self):
        b = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)),
            Body("b", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)),
        ]
        accel = bruteforce.compute_accelerations(b, G=1.0, softening=0.0)
        self.assertEqual(accel[0], Vec3(0, 0, 0))
        self.assertEqual(accel[1], Vec3(0, 0, 0))

    def test_close_encounter_without_softening_raises_clean_error(self):
        b = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)),
            Body("b", 1.0, Vec3(1e-103, 0, 0), Vec3(0, 0, 0)),
        ]
        with self.assertRaises(FloatingPointError):
            bruteforce.compute_accelerations(b, G=1.0, softening=0.0)

    def test_close_encounter_with_softening_does_not_raise(self):
        b = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)),
            Body("b", 1.0, Vec3(1e-103, 0, 0), Vec3(0, 0, 0)),
        ]
        accel = bruteforce.compute_accelerations(b, G=1.0, softening=1.0)
        self.assertTrue(accel[0].is_finite())

    def test_symmetric_random_cloud_zero_net_momentum_change(self):
        rng = random.Random(0)
        bodies = [
            Body(f"b{i}", rng.uniform(0.5, 3.0),
                 Vec3(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)), Vec3(0, 0, 0))
            for i in range(12)
        ]
        accel = bruteforce.compute_accelerations(bodies, G=1.0, softening=0.05)
        # Sum of m_i * a_i must be ~0 (internal forces cancel, Newton's 3rd law).
        total = Vec3(0, 0, 0)
        for body, a in zip(bodies, accel):
            total += a * body.mass
        self.assertAlmostEqual(total.norm(), 0.0, places=8)


if __name__ == "__main__":
    unittest.main()
