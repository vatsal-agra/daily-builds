import unittest

from orrery.vector import Vec3
from orrery.body import Body
from orrery import collision


class TestCollision(unittest.TestCase):
    def test_no_collision_when_far_apart(self):
        bodies = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0), radius=0.1),
            Body("b", 1.0, Vec3(10, 0, 0), Vec3(0, 0, 0), radius=0.1),
        ]
        merged = collision.resolve_collisions(bodies)
        self.assertFalse(merged)
        self.assertTrue(bodies[0].alive and bodies[1].alive)

    def test_overlapping_bodies_merge(self):
        bodies = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(1, 0, 0), radius=1.0),
            Body("b", 1.0, Vec3(0.5, 0, 0), Vec3(-1, 0, 0), radius=1.0),
        ]
        merged = collision.resolve_collisions(bodies)
        self.assertTrue(merged)
        alive = [b for b in bodies if b.alive]
        self.assertEqual(len(alive), 1)

    def test_merge_conserves_mass_and_momentum(self):
        bodies = [
            Body("a", 2.0, Vec3(0, 0, 0), Vec3(1, 0, 0), radius=1.0),
            Body("b", 3.0, Vec3(0.1, 0, 0), Vec3(-2, 1, 0), radius=1.0),
        ]
        p_before = bodies[0].momentum() + bodies[1].momentum()
        m_before = bodies[0].mass + bodies[1].mass
        collision.resolve_collisions(bodies)
        survivor = [b for b in bodies if b.alive][0]
        self.assertAlmostEqual(survivor.mass, m_before, places=10)
        self.assertAlmostEqual((survivor.momentum() - p_before).norm(), 0.0, places=8)

    def test_more_massive_body_survives(self):
        bodies = [
            Body("light", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0), radius=1.0),
            Body("heavy", 10.0, Vec3(0.5, 0, 0), Vec3(0, 0, 0), radius=1.0),
        ]
        collision.resolve_collisions(bodies)
        self.assertTrue(bodies[1].alive)
        self.assertFalse(bodies[0].alive)

    def test_radius_grows_by_constant_density_volume_rule(self):
        bodies = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0), radius=1.0),
            Body("b", 1.0, Vec3(0.5, 0, 0), Vec3(0, 0, 0), radius=1.0),
        ]
        collision.resolve_collisions(bodies)
        survivor = [b for b in bodies if b.alive][0]
        expected_r = (1.0 ** 3 + 1.0 ** 3) ** (1.0 / 3.0)
        self.assertAlmostEqual(survivor.radius, expected_r, places=10)

    def test_chain_merge_collapses_three_bodies_into_one(self):
        bodies = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0), radius=1.0),
            Body("b", 1.0, Vec3(0.5, 0, 0), Vec3(0, 0, 0), radius=1.0),
            Body("c", 1.0, Vec3(1.0, 0, 0), Vec3(0, 0, 0), radius=1.0),
        ]
        collision.resolve_collisions(bodies)
        alive = [b for b in bodies if b.alive]
        self.assertEqual(len(alive), 1)
        self.assertAlmostEqual(alive[0].mass, 3.0, places=10)
        self.assertEqual(alive[0].absorbed_count, 2)

    def test_log_records_events(self):
        bodies = [
            Body("a", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0), radius=1.0),
            Body("b", 1.0, Vec3(0.5, 0, 0), Vec3(0, 0, 0), radius=1.0),
        ]
        log = []
        collision.resolve_collisions(bodies, log=log, t=3.5)
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["t"], 3.5)
        self.assertIn(log[0]["survivor"], ("a", "b"))


if __name__ == "__main__":
    unittest.main()
