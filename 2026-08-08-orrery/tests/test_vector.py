import math
import unittest

from orrery.vector import Vec3


class TestVec3(unittest.TestCase):
    def test_add_sub_neg(self):
        a, b = Vec3(1, 2, 3), Vec3(4, 5, 6)
        self.assertEqual(a + b, Vec3(5, 7, 9))
        self.assertEqual(b - a, Vec3(3, 3, 3))
        self.assertEqual(-a, Vec3(-1, -2, -3))

    def test_scalar_mul_div(self):
        a = Vec3(1, 2, 3)
        self.assertEqual(a * 2, Vec3(2, 4, 6))
        self.assertEqual(2 * a, Vec3(2, 4, 6))
        self.assertEqual(a / 2, Vec3(0.5, 1.0, 1.5))

    def test_iadd(self):
        a = Vec3(1, 1, 1)
        a += Vec3(2, 2, 2)
        self.assertEqual(a, Vec3(3, 3, 3))

    def test_dot(self):
        self.assertEqual(Vec3(1, 2, 3).dot(Vec3(4, 5, 6)), 32)
        self.assertEqual(Vec3(1, 0, 0).dot(Vec3(0, 1, 0)), 0)

    def test_cross_orthogonal_and_right_handed(self):
        x, y, z = Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1)
        self.assertEqual(x.cross(y), z)
        self.assertEqual(y.cross(z), x)
        self.assertEqual(z.cross(x), y)

    def test_norm(self):
        self.assertAlmostEqual(Vec3(3, 4, 0).norm(), 5.0)
        self.assertEqual(Vec3(0, 0, 0).norm(), 0.0)
        self.assertAlmostEqual(Vec3(1, 2, 2).norm_sq(), 9.0)

    def test_normalized(self):
        n = Vec3(3, 4, 0).normalized()
        self.assertAlmostEqual(n.norm(), 1.0)
        # Degenerate zero vector doesn't crash, returns zero (not NaN).
        self.assertEqual(Vec3(0, 0, 0).normalized(), Vec3(0, 0, 0))

    def test_is_finite(self):
        self.assertTrue(Vec3(1, 2, 3).is_finite())
        self.assertFalse(Vec3(float("nan"), 0, 0).is_finite())
        self.assertFalse(Vec3(float("inf"), 0, 0).is_finite())

    def test_tuple_round_trip(self):
        v = Vec3(1.5, -2.5, 3.5)
        self.assertEqual(Vec3.from_tuple(v.to_tuple()), v)

    def test_copy_is_independent(self):
        a = Vec3(1, 2, 3)
        b = a.copy()
        b.x = 99
        self.assertEqual(a.x, 1)

    def test_equality_with_non_vec3(self):
        self.assertNotEqual(Vec3(1, 2, 3), (1, 2, 3))
        self.assertNotEqual(Vec3(1, 2, 3), None)


if __name__ == "__main__":
    unittest.main()
