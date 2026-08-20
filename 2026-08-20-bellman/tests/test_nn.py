import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from bellman.agents.nn import MLP, Adam, softmax


class TestGradCheck(unittest.TestCase):
    """Central finite-difference gradient checking: the real test that
    the hand-derived backward() equations are correct, not just that
    training loss goes down (which a wrong-but-decreasing gradient can
    also produce for a while)."""

    def _check(self, sizes, batch, seed=0):
        rng = np.random.default_rng(seed)
        mlp = MLP(sizes, seed=seed)
        x = rng.normal(size=(batch, sizes[0]))
        d_out = rng.normal(size=(batch, sizes[-1]))
        analytic, numeric = mlp.gradcheck(x, d_out, eps=1e-5)
        for name in analytic:
            a, n = analytic[name], numeric[name]
            max_abs_err = np.max(np.abs(a - n))
            denom = np.maximum(np.abs(a), np.abs(n)).max() + 1e-8
            rel_err = max_abs_err / denom
            self.assertLess(
                rel_err, 2e-4,
                f"{name}: analytic vs numeric gradient mismatch, rel_err={rel_err:.2e}, sizes={sizes}, batch={batch}",
            )

    def test_two_layer_small_batch(self):
        self._check([3, 5, 2], batch=1)

    def test_two_layer_batch(self):
        self._check([4, 6, 3], batch=8)

    def test_deep_network(self):
        self._check([3, 8, 8, 6, 2], batch=4)

    def test_single_layer_no_hidden(self):
        self._check([5, 1], batch=3)

    def test_wide_output(self):
        self._check([2, 4, 10], batch=5)


class TestForwardShapes(unittest.TestCase):
    def test_single_vector_squeezes_output(self):
        mlp = MLP([3, 4, 2], seed=0)
        out, _ = mlp.forward(np.array([1.0, 2.0, 3.0]))
        self.assertEqual(out.shape, (2,))

    def test_batch_preserves_leading_dim(self):
        mlp = MLP([3, 4, 2], seed=0)
        out, _ = mlp.forward(np.zeros((7, 3)))
        self.assertEqual(out.shape, (7, 2))

    def test_relu_only_on_hidden_layers(self):
        # A network whose only layer is the output layer must NOT apply
        # ReLU (real Q-values / logits can be negative).
        mlp = MLP([3, 2], seed=0)
        mlp.Ws[0][:] = -1.0
        mlp.bs[0][:] = 0.0
        out, _ = mlp.forward(np.ones(3))
        self.assertTrue(np.all(out < 0))

    def test_too_few_layers_rejected(self):
        with self.assertRaises(ValueError):
            MLP([5])


class TestAdamOptimizer(unittest.TestCase):
    def test_adam_drives_toy_regression_loss_down(self):
        """Overfit a tiny random regression target — not a rigorous proof
        of Adam's math, but catches a broken sign/update-rule bug
        immediately (loss would go up or flatline instead)."""
        rng = np.random.default_rng(0)
        mlp = MLP([4, 8, 1], seed=1)
        opt = Adam(mlp, lr=0.05)
        x = rng.normal(size=(16, 4))
        y = rng.normal(size=(16, 1))

        def mse():
            pred, _ = mlp.forward(x)
            return float(np.mean((pred - y) ** 2))

        loss0 = mse()
        for _ in range(200):
            pred, cache = mlp.forward(x)
            d_out = (pred - y)
            grads = mlp.backward(cache, d_out)
            opt.step(grads)
        loss1 = mse()
        self.assertLess(loss1, loss0 * 0.1)

    def test_set_params_like_copies_not_aliases(self):
        a = MLP([2, 3, 1], seed=0)
        b = MLP([2, 3, 1], seed=1)
        b.set_params_like(a)
        for wa, wb in zip(a.Ws, b.Ws):
            self.assertTrue(np.array_equal(wa, wb))
        a.Ws[0][0, 0] += 100.0
        self.assertNotEqual(a.Ws[0][0, 0], b.Ws[0][0, 0])  # must be a real copy


class TestSoftmax(unittest.TestCase):
    def test_rows_sum_to_one(self):
        x = np.array([[1.0, 2.0, 3.0], [0.0, 0.0, 0.0], [100.0, 0.0, -100.0]])
        p = softmax(x)
        np.testing.assert_allclose(p.sum(axis=1), np.ones(3), atol=1e-10)

    def test_numerically_stable_for_large_logits(self):
        x = np.array([[1000.0, 1000.1, 999.9]])
        p = softmax(x)
        self.assertTrue(np.all(np.isfinite(p)))
        self.assertAlmostEqual(p.sum(), 1.0, places=10)

    def test_uniform_for_equal_logits(self):
        p = softmax(np.zeros((1, 5)))
        np.testing.assert_allclose(p, np.full((1, 5), 0.2), atol=1e-10)


if __name__ == "__main__":
    unittest.main()
