import math
import unittest

from kinesis import vecmath as vm


class TestVecMath(unittest.TestCase):
    def test_add_sub_scale(self):
        self.assertEqual(vm.add((1, 2), (3, 4)), (4, 6))
        self.assertEqual(vm.sub((3, 4), (1, 2)), (2, 2))
        self.assertEqual(vm.scale((2, 3), 2.0), (4, 6))

    def test_dot_cross(self):
        self.assertEqual(vm.dot((1, 0), (0, 1)), 0)
        self.assertEqual(vm.dot((2, 3), (4, 5)), 2 * 4 + 3 * 5)
        self.assertEqual(vm.cross((1, 0), (0, 1)), 1)
        self.assertEqual(vm.cross((0, 1), (1, 0)), -1)

    def test_rotate_90(self):
        x, y = vm.rotate((1, 0), math.pi / 2)
        self.assertAlmostEqual(x, 0, places=9)
        self.assertAlmostEqual(y, 1, places=9)

    def test_rotate_full_circle_is_identity(self):
        p = (3.0, -2.0)
        rp = vm.rotate(p, 2 * math.pi)
        self.assertAlmostEqual(rp[0], p[0], places=9)
        self.assertAlmostEqual(rp[1], p[1], places=9)

    def test_normalize(self):
        nx, ny = vm.normalize((3.0, 4.0))
        self.assertAlmostEqual(nx, 0.6)
        self.assertAlmostEqual(ny, 0.8)

    def test_normalize_zero_vector_is_safe(self):
        self.assertEqual(vm.normalize((0.0, 0.0)), (0.0, 0.0))

    def test_perp_is_90deg_ccw(self):
        self.assertEqual(vm.perp((1, 0)), (0, 1))
        self.assertEqual(vm.perp((0, 1)), (-1, 0))

    def test_cross_sv_matches_rotate_derivative_convention(self):
        # d/dt rotate(v, theta) at theta=0 with angular rate w is w x v = cross_sv(w, v)
        v = (2.0, 0.0)
        w = 1.0
        eps = 1e-6
        numeric = vm.scale(vm.sub(vm.rotate(v, eps), v), 1.0 / eps)
        analytic = vm.cross_sv(w, v)
        self.assertAlmostEqual(numeric[0], analytic[0], places=3)
        self.assertAlmostEqual(numeric[1], analytic[1], places=3)


if __name__ == "__main__":
    unittest.main()
