import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from loom.tensor import Tensor, concatenate, no_grad  # noqa: E402

np.random.seed(0)


def numeric_grad(f, x, eps=1e-6):
    """Central-difference numeric gradient of scalar function f w.r.t. array x."""
    grad = np.zeros_like(x)
    it = np.nditer(x, flags=["multi_index"])
    while not it.finished:
        idx = it.multi_index
        orig = x[idx]
        x[idx] = orig + eps
        plus = f()
        x[idx] = orig - eps
        minus = f()
        x[idx] = orig
        grad[idx] = (plus - minus) / (2 * eps)
        it.iternext()
    return grad


class GradCheckMixin:
    def assert_gradcheck(self, build_fn, *shapes, tol=1e-4):
        """build_fn(*tensors) -> scalar Tensor. Checks analytic vs numeric grad
        for every input tensor."""
        arrays = [np.random.randn(*s) * 0.5 for s in shapes]

        def make_tensors():
            return [Tensor(a.copy(), requires_grad=True) for a in arrays]

        tensors = make_tensors()
        out = build_fn(*tensors)
        out.backward()
        analytic = [t.grad.copy() for t in tensors]

        for i, arr in enumerate(arrays):
            def f(i=i):
                ts = make_tensors()
                for j, a in enumerate(arrays):
                    ts[j].data = a
                out = build_fn(*ts)
                return out.data.copy()

            numeric = numeric_grad(f, arr)
            self.assertTrue(
                np.allclose(analytic[i], numeric, atol=tol, rtol=tol),
                f"grad mismatch for input {i}: max diff "
                f"{np.max(np.abs(analytic[i] - numeric))}",
            )


class TestOps(unittest.TestCase, GradCheckMixin):
    def test_add_broadcast(self):
        self.assert_gradcheck(lambda a, b: (a + b).sum(), (3, 4), (4,))

    def test_sub(self):
        self.assert_gradcheck(lambda a, b: (a - b).sum(), (3, 4), (3, 4))

    def test_mul_broadcast(self):
        self.assert_gradcheck(lambda a, b: (a * b).sum(), (3, 4), (1, 4))

    def test_div(self):
        arrays_ok = True
        self.assert_gradcheck(lambda a, b: (a / b).sum(), (3, 4), (3, 4))

    def test_neg(self):
        self.assert_gradcheck(lambda a: (-a).sum(), (5,))

    def test_pow(self):
        def build(a):
            return (a.pow(3)).sum()

        arr_shapes = [(4,)]
        self.assert_gradcheck(build, *arr_shapes)

    def test_matmul(self):
        self.assert_gradcheck(lambda a, b: (a @ b).sum(), (3, 4), (4, 5))

    def test_matmul_batched(self):
        self.assert_gradcheck(lambda a, b: (a @ b).sum(), (2, 3, 4), (2, 4, 5))

    def test_reshape(self):
        self.assert_gradcheck(lambda a: a.reshape(2, 6).sum(), (3, 4))

    def test_transpose(self):
        self.assert_gradcheck(lambda a: a.transpose(1, 0).sum(), (3, 4))

    def test_sum_axis(self):
        self.assert_gradcheck(lambda a: a.sum(axis=1).sum(), (3, 4))

    def test_mean(self):
        self.assert_gradcheck(lambda a: a.mean(), (3, 4))

    def test_mean_axis_keepdims(self):
        self.assert_gradcheck(lambda a: (a - a.mean(axis=-1, keepdims=True)).sum(), (3, 4))

    def test_exp(self):
        self.assert_gradcheck(lambda a: a.exp().sum(), (4,))

    def test_log(self):
        def build(a):
            return (a.pow(2) + 0.5).log().sum()

        self.assert_gradcheck(build, (4,))

    def test_sqrt(self):
        def build(a):
            return (a.pow(2) + 1.0).sqrt().sum()

        self.assert_gradcheck(build, (4,))

    def test_tanh(self):
        self.assert_gradcheck(lambda a: a.tanh().sum(), (5,))

    def test_relu(self):
        self.assert_gradcheck(lambda a: a.relu().sum(), (6,))

    def test_softmax(self):
        def build(a):
            s = a.softmax(axis=-1)
            return (s * s).sum()

        self.assert_gradcheck(build, (3, 5))

    def test_concatenate(self):
        def build(a, b):
            return concatenate([a, b], axis=-1).sum()

        self.assert_gradcheck(build, (3, 2), (3, 4))

    def test_cross_entropy(self):
        targets = np.array([1, 0, 2])
        arrays = [np.random.randn(3, 4)]

        def build(logits):
            return logits.cross_entropy(targets)

        self.assert_gradcheck(build, (3, 4))

    def test_embedding(self):
        idx = np.array([0, 2, 1, 2])

        def build(weight):
            return weight.embedding(idx).sum()

        self.assert_gradcheck(build, (3, 5))

    def test_embedding_duplicate_index_accumulates(self):
        # index 2 appears twice: gradient must accumulate, not overwrite
        idx = np.array([2, 2])
        w = Tensor(np.zeros((3, 2)), requires_grad=True)
        out = w.embedding(idx)
        (out * Tensor(np.array([[1.0, 1.0], [1.0, 1.0]]))).sum().backward()
        self.assertTrue(np.allclose(w.grad[2], [2.0, 2.0]))
        self.assertTrue(np.allclose(w.grad[0], [0.0, 0.0]))

    def test_no_grad_disables_graph(self):
        with no_grad():
            a = Tensor(np.ones(3), requires_grad=True)
            b = (a * 2).sum()
        self.assertFalse(b.requires_grad)

    def test_deep_chain_backward(self):
        # a diamond graph: same tensor used twice must accumulate gradients
        a = Tensor(np.array(2.0), requires_grad=True)
        b = a * a  # b = a^2, db/da = 2a
        c = b * a  # c = a^3, dc/da = 3a^2
        c.backward()
        self.assertTrue(np.allclose(a.grad, [3 * 2.0 ** 2]))


if __name__ == "__main__":
    unittest.main()
