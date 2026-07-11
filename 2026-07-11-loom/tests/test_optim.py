import unittest

import numpy as np

from loom.optim import Adam
from loom.tensor import Tensor


class TestAdam(unittest.TestCase):
    def test_converges_on_convex_quadratic(self):
        target = np.array([3.0, -2.0, 5.0, 0.25])
        p = Tensor(np.zeros(4), requires_grad=True)
        opt = Adam([p], lr=0.1)
        for _ in range(400):
            opt.zero_grad()
            diff = p - target
            loss = (diff * diff).sum()
            loss.backward()
            opt.step()
        np.testing.assert_allclose(p.data, target, atol=1e-3)

    def test_zero_grad_sets_none(self):
        p = Tensor(np.zeros(2), requires_grad=True)
        opt = Adam([p])
        p.grad = np.ones(2)
        opt.zero_grad()
        self.assertIsNone(p.grad)

    def test_step_skips_params_with_no_grad(self):
        p1 = Tensor(np.array([1.0]), requires_grad=True)
        p2 = Tensor(np.array([2.0]), requires_grad=True)
        opt = Adam([p1, p2], lr=0.1)
        p1.grad = np.array([1.0])
        # p2.grad left None
        opt.step()
        self.assertNotEqual(p1.data[0], 1.0)
        self.assertEqual(p2.data[0], 2.0)

    def test_clip_grad_norm_reduces_large_gradients(self):
        p = Tensor(np.zeros(3), requires_grad=True)
        opt = Adam([p])
        p.grad = np.array([3.0, 4.0, 0.0])  # norm = 5
        total_norm = opt.clip_grad_norm(max_norm=1.0)
        self.assertAlmostEqual(total_norm, 5.0, places=5)
        new_norm = np.linalg.norm(p.grad)
        self.assertAlmostEqual(new_norm, 1.0, places=4)

    def test_clip_grad_norm_leaves_small_gradients_untouched(self):
        p = Tensor(np.zeros(3), requires_grad=True)
        opt = Adam([p])
        p.grad = np.array([0.1, 0.0, 0.0])
        opt.clip_grad_norm(max_norm=5.0)
        np.testing.assert_allclose(p.grad, [0.1, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
