import unittest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loom.tensor import Tensor
from loom.optim import Adam, lr_schedule


class TestAdam(unittest.TestCase):
    def test_reduces_quadratic_loss(self):
        np.random.seed(0)
        x = Tensor(np.array([5.0, -3.0]), requires_grad=True)
        opt = Adam([x], lr=0.1)
        losses = []
        for _ in range(200):
            opt.zero_grad()
            loss = (x * x).sum()
            loss.backward()
            opt.step()
            losses.append(loss.item())
        self.assertLess(losses[-1], losses[0] * 1e-3)
        np.testing.assert_allclose(x.data, np.zeros(2), atol=1e-2)

    def test_clip_grad_norm_shrinks_large_grads(self):
        x = Tensor(np.array([1.0]), requires_grad=True)
        opt = Adam([x])
        x.grad = np.array([100.0])
        total = opt.clip_grad_norm(1.0)
        self.assertAlmostEqual(total, 100.0)
        self.assertAlmostEqual(float(x.grad[0]), 1.0, places=5)

    def test_zero_grad_clears(self):
        x = Tensor(np.array([1.0]), requires_grad=True)
        opt = Adam([x])
        x.grad = np.array([5.0])
        opt.zero_grad()
        self.assertIsNone(x.grad)


class TestLRSchedule(unittest.TestCase):
    def test_warmup_then_decay(self):
        base = 1e-3
        warm = 10
        total = 100
        lrs = [lr_schedule(s, warm, total, base) for s in range(total)]
        # increasing through warmup
        self.assertLess(lrs[0], lrs[warm - 1])
        # decaying after warmup, ends near min ratio
        self.assertGreater(lrs[warm], lrs[-1])
        self.assertLessEqual(lrs[-1], base)


if __name__ == "__main__":
    unittest.main()
