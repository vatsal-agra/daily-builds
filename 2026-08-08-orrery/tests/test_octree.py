import random
import unittest

from orrery.vector import Vec3
from orrery.body import Body
from orrery import bruteforce, octree


class TestOctree(unittest.TestCase):
    def test_empty_and_single_body(self):
        self.assertEqual(octree.compute_accelerations([], G=1.0, theta=0.5), [])
        one = [Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0))]
        self.assertEqual(octree.compute_accelerations(one, G=1.0, theta=0.5), [Vec3(0, 0, 0)])

    def test_negative_theta_rejected(self):
        one = [Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0))]
        with self.assertRaises(ValueError):
            octree.compute_accelerations(one, G=1.0, theta=-0.1)

    def test_theta_zero_matches_bruteforce_exactly(self):
        rng = random.Random(3)
        bodies = [
            Body(f"b{i}", rng.uniform(0.5, 3.0),
                 Vec3(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)), Vec3(0, 0, 0))
            for i in range(35)
        ]
        a_bf = bruteforce.compute_accelerations(bodies, G=1.0, softening=0.02)
        a_bh = octree.compute_accelerations(bodies, G=1.0, theta=0.0, softening=0.02)
        max_err = max((a - b).norm() for a, b in zip(a_bf, a_bh))
        self.assertLess(max_err, 1e-9)

    def test_moderate_theta_is_close_approximation(self):
        rng = random.Random(4)
        bodies = [
            Body(f"b{i}", rng.uniform(0.5, 3.0),
                 Vec3(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)), Vec3(0, 0, 0))
            for i in range(40)
        ]
        a_bf = bruteforce.compute_accelerations(bodies, G=1.0, softening=0.02)
        a_bh = octree.compute_accelerations(bodies, G=1.0, theta=0.5, softening=0.02)
        rel_errs = [(a - b).norm() / max(a.norm(), 1e-12) for a, b in zip(a_bf, a_bh)]
        self.assertLess(max(rel_errs), 0.15)

    def test_coincident_bodies_do_not_crash_build(self):
        bodies = [Body(f"b{i}", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)) for i in range(5)]
        accel = octree.compute_accelerations(bodies, G=1.0, theta=0.5, softening=0.1)
        self.assertEqual(len(accel), 5)
        for a in accel:
            self.assertTrue(a.is_finite())

    def test_dead_bodies_get_zero_and_are_excluded_from_tree(self):
        bodies = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)),
            Body("b", 1.0, Vec3(1, 0, 0), Vec3(0, 0, 0)),
        ]
        bodies[1].alive = False
        accel = octree.compute_accelerations(bodies, G=1.0, theta=0.5)
        self.assertEqual(accel[0], Vec3(0, 0, 0))
        self.assertEqual(accel[1], Vec3(0, 0, 0))

    def test_close_encounter_without_softening_raises_clean_error(self):
        bodies = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0)),
            Body("b", 1.0, Vec3(1e-103, 0, 0), Vec3(0, 0, 0)),
        ]
        with self.assertRaises(FloatingPointError):
            octree.compute_accelerations(bodies, G=1.0, theta=0.5, softening=0.0)

    def test_build_tree_none_for_all_dead(self):
        bodies = [Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0))]
        bodies[0].alive = False
        self.assertIsNone(octree.build_tree(bodies))

    def test_node_count_grows_with_body_count(self):
        rng = random.Random(5)
        few = [Body(f"b{i}", 1.0, Vec3(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)), Vec3(0, 0, 0)) for i in range(4)]
        many = [Body(f"b{i}", 1.0, Vec3(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)), Vec3(0, 0, 0)) for i in range(60)]
        self.assertGreaterEqual(octree.node_count(octree.build_tree(many)), octree.node_count(octree.build_tree(few)))

    def test_total_mass_conserved_in_tree(self):
        rng = random.Random(6)
        bodies = [
            Body(f"b{i}", rng.uniform(0.5, 3.0), Vec3(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5)), Vec3(0, 0, 0))
            for i in range(25)
        ]
        root = octree.build_tree(bodies)
        self.assertAlmostEqual(root.mass, sum(b.mass for b in bodies), places=8)


if __name__ == "__main__":
    unittest.main()
