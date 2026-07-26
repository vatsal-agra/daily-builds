import unittest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loom.tensor import Tensor
from loom import gradcheck


class TestGradcheck(unittest.TestCase):
    def test_all_ops(self):
        results = gradcheck.run_all(verbose=False)
        failed = [name for name, ok in results.items() if not ok]
        self.assertEqual(failed, [], f"gradient check failed for ops: {failed}")
        self.assertGreaterEqual(len(results), 20)


class TestTensorBasics(unittest.TestCase):
    def test_add_shapes(self):
        a = Tensor(np.ones((2, 3)))
        b = Tensor(np.ones((2, 3)))
        c = a + b
        np.testing.assert_array_equal(c.data, np.full((2, 3), 2.0))

    def test_backward_accumulates_multi_use(self):
        x = Tensor(np.array([2.0, 3.0]), requires_grad=True)
        y = (x * x).sum() + x.sum()  # dy/dx = 2x + 1
        y.backward()
        np.testing.assert_allclose(x.grad, 2 * x.data + 1, atol=1e-8)

    def test_no_grad_leaf_does_not_crash(self):
        x = Tensor(np.array([1.0, 2.0]), requires_grad=True)
        const = Tensor(np.array([5.0, 5.0]), requires_grad=False)
        y = (x * const).sum()
        y.backward()
        np.testing.assert_allclose(x.grad, const.data)
        self.assertIsNone(const.grad)

    def test_matmul_shape(self):
        a = Tensor(np.random.randn(3, 4))
        b = Tensor(np.random.randn(4, 5))
        c = a.matmul(b)
        self.assertEqual(c.shape, (3, 5))

    def test_softmax_sums_to_one(self):
        x = Tensor(np.random.randn(4, 6))
        s = x.softmax(axis=-1)
        np.testing.assert_allclose(s.data.sum(axis=-1), np.ones(4), atol=1e-8)

    def test_layernorm_zero_mean_unit_var(self):
        x = Tensor(np.random.randn(5, 8) * 10 + 3)
        gamma = Tensor(np.ones(8))
        beta = Tensor(np.zeros(8))
        y = x.layernorm(gamma, beta)
        np.testing.assert_allclose(y.data.mean(axis=-1), np.zeros(5), atol=1e-6)
        np.testing.assert_allclose(y.data.std(axis=-1), np.ones(5), atol=1e-3)

    def test_gather0_and_slice(self):
        x = Tensor(np.arange(12).reshape(4, 3).astype(float))
        g = x[np.array([0, 2])]
        np.testing.assert_array_equal(g.data, x.data[[0, 2]])
        s = x[1:3]
        np.testing.assert_array_equal(s.data, x.data[1:3])

    def test_concat_matches_numpy(self):
        a = Tensor(np.ones((2, 3)))
        b = Tensor(np.zeros((2, 2)))
        c = Tensor.concat([a, b], axis=1)
        np.testing.assert_array_equal(c.data, np.concatenate([a.data, b.data], axis=1))


if __name__ == "__main__":
    unittest.main()
