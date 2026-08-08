import unittest

from orrery import scenarios
from orrery.vector import Vec3
from orrery.integrator import total_momentum


class TestScenarios(unittest.TestCase):
    def test_registry_all_buildable(self):
        for name in scenarios.REGISTRY:
            sc = scenarios.build(name)
            self.assertGreater(len(sc.bodies), 0)
            self.assertGreater(sc.G, 0)
            self.assertGreater(sc.recommended_dt, 0)

    def test_unknown_scenario_raises(self):
        with self.assertRaises(ValueError):
            scenarios.build("not_a_real_scenario")

    def test_solar_system_has_nine_bodies_and_zero_net_momentum(self):
        sc = scenarios.solar_system()
        self.assertEqual(len(sc.bodies), 9)
        self.assertEqual(sc.bodies[0].name, "Sun")
        p = total_momentum(sc.bodies)
        self.assertLess(p.norm(), 1e-12)

    def test_binary_star_zero_net_momentum(self):
        sc = scenarios.binary_star()
        self.assertEqual(len(sc.bodies), 2)
        p = total_momentum(sc.bodies)
        self.assertLess(p.norm(), 1e-10)

    def test_figure_eight_three_equal_masses(self):
        sc = scenarios.figure_eight()
        self.assertEqual(len(sc.bodies), 3)
        masses = {b.mass for b in sc.bodies}
        self.assertEqual(masses, {1.0})
        self.assertEqual(sc.G, 1.0)

    def test_plummer_cluster_body_count_and_seed_determinism(self):
        sc1 = scenarios.plummer_cluster(n=20, seed=11)
        sc2 = scenarios.plummer_cluster(n=20, seed=11)
        self.assertEqual(len(sc1.bodies), 20)
        for b1, b2 in zip(sc1.bodies, sc2.bodies):
            self.assertEqual(b1.position, b2.position)
            self.assertEqual(b1.velocity, b2.velocity)

    def test_plummer_cluster_different_seed_differs(self):
        sc1 = scenarios.plummer_cluster(n=10, seed=1)
        sc2 = scenarios.plummer_cluster(n=10, seed=2)
        self.assertNotEqual(sc1.bodies[0].position.to_tuple(), sc2.bodies[0].position.to_tuple())

    def test_plummer_cluster_rejects_nonpositive_n(self):
        with self.assertRaises(ValueError):
            scenarios.plummer_cluster(n=0)
        with self.assertRaises(ValueError):
            scenarios.plummer_cluster(n=-5)

    def test_galaxy_collision_rejects_nonpositive_n(self):
        with self.assertRaises(ValueError):
            scenarios.galaxy_collision(n_per_galaxy=0)
        with self.assertRaises(ValueError):
            scenarios.galaxy_collision(n_per_galaxy=-1)

    def test_galaxy_collision_two_named_groups(self):
        sc = scenarios.galaxy_collision(n_per_galaxy=8, seed=2)
        self.assertEqual(len(sc.bodies), 16)
        a_count = sum(1 for b in sc.bodies if b.name.startswith("A_"))
        b_count = sum(1 for b in sc.bodies if b.name.startswith("B_"))
        self.assertEqual(a_count, 8)
        self.assertEqual(b_count, 8)

    def test_plummer_single_body_recenters_to_origin_at_rest(self):
        # A lone body's own position/velocity *is* the center of mass, so
        # recentering the cluster on its COM sends it to the origin at rest.
        sc = scenarios.plummer_cluster(n=1, seed=1)
        self.assertAlmostEqual(sc.bodies[0].position.norm(), 0.0, places=9)
        self.assertAlmostEqual(sc.bodies[0].velocity.norm(), 0.0, places=9)


if __name__ == "__main__":
    unittest.main()
