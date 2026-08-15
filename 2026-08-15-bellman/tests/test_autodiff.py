import math
import random
import unittest

from bellman.autodiff import Value, softmax


def numerical_grad(f, x, eps=1e-6):
    return (f(x + eps) - f(x - eps)) / (2 * eps)


class TestAutodiff(unittest.TestCase):
    def _check(self, f_value, f_float, x0, eps_tol=1e-4):
        """f_value(Value) -> Value, f_float(float) -> float. Same math, one
        traced through the autodiff graph, one plain Python -- gradient from
        backward() must match a central finite-difference estimate."""
        x = Value(x0)
        y = f_value(x)
        y.backward()
        numeric = numerical_grad(f_float, x0)
        self.assertAlmostEqual(x.grad, numeric, delta=eps_tol * max(1.0, abs(numeric)))

    def test_add_mul_sub(self):
        self._check(lambda x: x * 3.0 + 2.0, lambda x: x * 3.0 + 2.0, 1.3)
        self._check(lambda x: (x + 2.0) * (x - 1.0), lambda x: (x + 2.0) * (x - 1.0), 0.7)
        self._check(lambda x: 5.0 - x * x, lambda x: 5.0 - x * x, -0.4)

    def test_div(self):
        self._check(lambda x: (x + 1.0) / (x + 3.0), lambda x: (x + 1.0) / (x + 3.0), 0.5)
        self._check(lambda x: 4.0 / x, lambda x: 4.0 / x, 2.0)

    def test_pow(self):
        self._check(lambda x: x ** 3, lambda x: x ** 3, 1.5)
        self._check(lambda x: x ** -2, lambda x: x ** -2, 1.5)

    def test_exp_log(self):
        self._check(lambda x: x.exp(), lambda x: math.exp(x), 0.6)
        self._check(lambda x: (x * 2.0 + 1.0).log(), lambda x: math.log(x * 2.0 + 1.0), 0.9)

    def test_tanh(self):
        self._check(lambda x: x.tanh(), lambda x: math.tanh(x), 0.3)

    def test_relu(self):
        # relu is non-differentiable at 0; test away from the kink on both sides.
        self._check(lambda x: x.relu() * 2.0, lambda x: max(x, 0.0) * 2.0, 1.2)
        self._check(lambda x: x.relu() * 2.0, lambda x: max(x, 0.0) * 2.0, -1.2)

    def test_composite_graph_shared_subexpression(self):
        # y = (a*b + a) where a is reused -- gradient must correctly sum both paths.
        a = Value(2.0)
        b = Value(3.0)
        y = a * b + a
        y.backward()
        # dy/da = b + 1 = 4, dy/db = a = 2
        self.assertAlmostEqual(a.grad, 4.0)
        self.assertAlmostEqual(b.grad, 2.0)

    def test_softmax_sums_to_one_and_gradients_finite(self):
        logits = [Value(1.0), Value(2.0), Value(0.5)]
        probs = softmax(logits)
        total = sum(p.data for p in probs)
        self.assertAlmostEqual(total, 1.0, places=6)

        loss = -probs[1].log()
        loss.backward()
        for lg in logits:
            self.assertTrue(math.isfinite(lg.grad))

    def test_softmax_matches_manual_computation(self):
        rng = random.Random(0)
        raw = [rng.uniform(-3, 3) for _ in range(5)]
        logits = [Value(x) for x in raw]
        probs = [p.data for p in softmax(logits)]
        m = max(raw)
        expected = [math.exp(x - m) for x in raw]
        s = sum(expected)
        expected = [e / s for e in expected]
        for p, e in zip(probs, expected):
            self.assertAlmostEqual(p, e, places=6)


if __name__ == "__main__":
    unittest.main()
