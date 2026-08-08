import unittest

from orrery.vector import Vec3
from orrery.body import Body


class TestBody(unittest.TestCase):
    def test_basic_construction(self):
        b = Body("Earth", 1.0, Vec3(1, 0, 0), Vec3(0, 1, 0))
        self.assertEqual(b.name, "Earth")
        self.assertEqual(b.mass, 1.0)
        self.assertTrue(b.alive)
        self.assertEqual(b.absorbed_count, 0)
        self.assertGreater(b.radius, 0.0)

    def test_rejects_nonpositive_mass(self):
        with self.assertRaises(ValueError):
            Body("x", 0.0, Vec3(0, 0, 0), Vec3(0, 0, 0))
        with self.assertRaises(ValueError):
            Body("x", -1.0, Vec3(0, 0, 0), Vec3(0, 0, 0))

    def test_rejects_non_finite_state(self):
        with self.assertRaises(ValueError):
            Body("x", 1.0, Vec3(float("nan"), 0, 0), Vec3(0, 0, 0))
        with self.assertRaises(ValueError):
            Body("x", 1.0, Vec3(0, 0, 0), Vec3(float("inf"), 0, 0))

    def test_rejects_non_vec3_position(self):
        with self.assertRaises(TypeError):
            Body("x", 1.0, (0, 0, 0), Vec3(0, 0, 0))

    def test_momentum_and_kinetic_energy(self):
        b = Body("x", 2.0, Vec3(0, 0, 0), Vec3(3, 0, 0))
        self.assertEqual(b.momentum(), Vec3(6, 0, 0))
        self.assertEqual(b.kinetic_energy(), 0.5 * 2.0 * 9.0)

    def test_radius_scales_with_mass(self):
        small = Body("s", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0))
        big = Body("b", 8.0, Vec3(0, 0, 0), Vec3(0, 0, 0))
        # constant density: mass x8 -> radius x2
        self.assertAlmostEqual(big.radius / small.radius, 2.0, places=6)

    def test_explicit_radius_overrides_default(self):
        b = Body("x", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0), radius=42.0)
        self.assertEqual(b.radius, 42.0)

    def test_copy_is_independent(self):
        b = Body("x", 1.0, Vec3(0, 0, 0), Vec3(0, 0, 0))
        c = b.copy()
        c.position.x = 99
        c.mass = 5
        self.assertEqual(b.position.x, 0)
        self.assertEqual(b.mass, 1.0)

    def test_to_dict_from_dict_round_trip(self):
        b = Body("Mars", 3.2, Vec3(1, 2, 3), Vec3(-1, -2, -3), color="#ff0000")
        b.alive = False
        b.absorbed_count = 2
        d = b.to_dict()
        b2 = Body.from_dict(d)
        self.assertEqual(b2.name, "Mars")
        self.assertEqual(b2.mass, 3.2)
        self.assertEqual(b2.position, Vec3(1, 2, 3))
        self.assertEqual(b2.velocity, Vec3(-1, -2, -3))
        self.assertEqual(b2.color, "#ff0000")
        self.assertFalse(b2.alive)
        self.assertEqual(b2.absorbed_count, 2)

    def test_from_dict_tolerates_missing_optional_fields(self):
        d = {"name": "x", "mass": 1.0, "position": (0, 0, 0), "velocity": (0, 0, 0)}
        b = Body.from_dict(d)
        self.assertTrue(b.alive)
        self.assertEqual(b.absorbed_count, 0)
        self.assertEqual(b.color, "#e8e8e8")


if __name__ == "__main__":
    unittest.main()
