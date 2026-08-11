import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bellman.agents.nn import MLP, Dense, Adam


def numerical_gradient_check(mlp, x, out_idx, eps=1e-5):
    """Central-difference check of every W/b parameter against the
    analytic gradient produced by mlp.backward()."""
    out = mlp.forward(x)
    d_out = [0.0] * len(out)
    d_out[out_idx] = 1.0
    grads = mlp.backward(d_out)

    max_err = 0.0
    for li, layer in enumerate(mlp.layers):
        dW, db = grads[li]
        for o in range(layer.n_out):
            for i in range(layer.n_in):
                orig = layer.W[o][i]
                layer.W[o][i] = orig + eps
                lp = mlp.forward(x)[out_idx]
                layer.W[o][i] = orig - eps
                lm = mlp.forward(x)[out_idx]
                layer.W[o][i] = orig
                numgrad = (lp - lm) / (2 * eps)
                max_err = max(max_err, abs(numgrad - dW[o][i]))
            orig_b = layer.b[o]
            layer.b[o] = orig_b + eps
            lp = mlp.forward(x)[out_idx]
            layer.b[o] = orig_b - eps
            lm = mlp.forward(x)[out_idx]
            layer.b[o] = orig_b
            numgrad_b = (lp - lm) / (2 * eps)
            max_err = max(max_err, abs(numgrad_b - db[o]))
    return max_err


class TestDenseLayer(unittest.TestCase):
    def test_relu_zeroes_negative_preactivations(self):
        layer = Dense(2, 3, activation="relu", rng=random.Random(0))
        layer.W = [[1.0, 0.0], [-1.0, 0.0], [0.0, 0.0]]
        layer.b = [0.0, 0.0, -5.0]
        out = layer.forward([2.0, 0.0])
        self.assertEqual(out, [2.0, 0.0, 0.0])  # relu(2), relu(-2), relu(-5)

    def test_linear_layer_passes_through(self):
        layer = Dense(2, 1, activation="linear", rng=random.Random(0))
        layer.W = [[2.0, -1.0]]
        layer.b = [0.5]
        out = layer.forward([3.0, 1.0])
        self.assertAlmostEqual(out[0], 2 * 3.0 - 1.0 * 1.0 + 0.5)


class TestGradientCorrectness(unittest.TestCase):
    def test_two_layer_mlp_gradients_match_finite_differences(self):
        mlp = MLP([3, 5, 2], seed=1)
        x = [0.3, -0.2, 0.7]
        for out_idx in (0, 1):
            err = numerical_gradient_check(mlp, x, out_idx)
            self.assertLess(err, 1e-6)

    def test_three_layer_mlp_gradients_match_finite_differences(self):
        mlp = MLP([4, 8, 6, 3], seed=2)
        x = [0.1, -0.4, 0.9, 0.05]
        for out_idx in range(3):
            err = numerical_gradient_check(mlp, x, out_idx)
            self.assertLess(err, 1e-6)

    def test_gradients_near_a_relu_kink_are_still_sane(self):
        # small, generic (not exactly on the z=0 kink, where relu is
        # genuinely non-differentiable and finite differences are
        # meaningless by construction) inputs -- exercises units whose
        # pre-activation sits close to zero without landing exactly on it
        mlp = MLP([2, 4, 1], seed=3)
        x = [0.001, -0.002]
        err = numerical_gradient_check(mlp, x, 0, eps=1e-6)
        self.assertLess(err, 1e-4)


class TestAdamOptimizer(unittest.TestCase):
    def test_adam_reduces_a_simple_quadratic_loss(self):
        # fit a fixed 1-layer linear model to a single target with Adam;
        # the loss (0.5*(pred-target)^2) should monotonically-ish decrease
        mlp = MLP([2, 1], seed=0)
        opt = Adam(mlp, lr=0.1)
        x = [1.0, -1.0]
        target = 3.0

        losses = []
        for _ in range(200):
            pred = mlp.forward(x)[0]
            err = pred - target
            losses.append(0.5 * err * err)
            grads = mlp.backward([err])
            opt.step(mlp, grads)

        self.assertLess(losses[-1], losses[0] * 0.01)
        self.assertLess(losses[-1], 1e-4)

    def test_clone_and_load_from_produce_independent_but_equal_copies(self):
        mlp = MLP([3, 4, 2], seed=5)
        clone = mlp.clone()
        # mutate the original; the clone must not change
        mlp.layers[0].W[0][0] += 100.0
        self.assertNotEqual(mlp.layers[0].W[0][0], clone.layers[0].W[0][0])

        other = MLP([3, 4, 2], seed=999)
        other.load_from(mlp)
        for la, lb in zip(mlp.layers, other.layers):
            self.assertEqual(la.W, lb.W)
            self.assertEqual(la.b, lb.b)


if __name__ == "__main__":
    unittest.main()
