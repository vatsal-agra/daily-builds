import unittest

import numpy as np

from loom import gradcheck
from loom.tensor import Tensor, embedding


def rt(*shape, seed=0, offset=0.0):
    rng = np.random.default_rng(seed)
    return Tensor(rng.standard_normal(shape) + offset, requires_grad=True)


class TestArithmetic(unittest.TestCase):
    def test_add_forward(self):
        a = Tensor([1.0, 2.0, 3.0])
        b = Tensor([10.0, 20.0, 30.0])
        np.testing.assert_allclose((a + b).data, [11, 22, 33])

    def test_add_grad_matches_finite_difference(self):
        a, b = rt(3, 4, seed=1), rt(3, 4, seed=2)
        ok, report = gradcheck.check(lambda: (a + b).sum(), [a, b])
        self.assertTrue(ok, "\n".join(report))

    def test_add_broadcast_grad(self):
        a = rt(3, 4, seed=1)
        b = rt(4, seed=2)  # broadcasts over the batch dim
        ok, report = gradcheck.check(lambda: (a + b).sum(), [a, b])
        self.assertTrue(ok, "\n".join(report))

    def test_sub_neg_mul_div_grad(self):
        a, b = rt(3, 4, seed=1, offset=3.0), rt(3, 4, seed=2, offset=3.0)  # keep away from 0
        for fn in [
            lambda: (a - b).sum(),
            lambda: (-a).sum(),
            lambda: (a * b).sum(),
            lambda: (a / b).sum(),
        ]:
            ok, report = gradcheck.check(fn, [a, b])
            self.assertTrue(ok, "\n".join(report))

    def test_pow_grad(self):
        a = rt(5, seed=3, offset=3.0)
        ok, report = gradcheck.check(lambda: (a ** 3).sum(), [a])
        self.assertTrue(ok, "\n".join(report))

    def test_division_by_scalar_matches_manual(self):
        a = Tensor([2.0, 4.0, 6.0], requires_grad=True)
        out = (a / 2.0).sum()
        out.backward()
        np.testing.assert_allclose(a.grad, [0.5, 0.5, 0.5])


class TestMatmul(unittest.TestCase):
    def test_2d_matmul_grad(self):
        a, b = rt(3, 4, seed=1), rt(4, 5, seed=2)
        ok, report = gradcheck.check(lambda: (a @ b).sum(), [a, b])
        self.assertTrue(ok, "\n".join(report))

    def test_batched_matmul_grad(self):
        a, b = rt(2, 3, 4, seed=1), rt(2, 4, 5, seed=2)
        ok, report = gradcheck.check(lambda: (a @ b).sum(), [a, b])
        self.assertTrue(ok, "\n".join(report))

    def test_matmul_broadcast_over_batch_grad(self):
        # (2, 3, 4) @ (4, 5): b has no batch dim, gets broadcast
        a, b = rt(2, 3, 4, seed=1), rt(4, 5, seed=2)
        ok, report = gradcheck.check(lambda: (a @ b).sum(), [a, b])
        self.assertTrue(ok, "\n".join(report))

    def test_matmul_correctness_vs_numpy(self):
        rng = np.random.default_rng(0)
        an = rng.standard_normal((3, 4))
        bn = rng.standard_normal((4, 5))
        out = Tensor(an) @ Tensor(bn)
        np.testing.assert_allclose(out.data, an @ bn)


class TestShapeOps(unittest.TestCase):
    def test_reshape_grad(self):
        a = rt(2, 3, 4, seed=1)
        ok, report = gradcheck.check(lambda: a.reshape(6, 4).sum(), [a])
        self.assertTrue(ok, "\n".join(report))

    def test_transpose_grad(self):
        a = rt(2, 3, 4, seed=1)
        ok, report = gradcheck.check(lambda: a.transpose(0, 2, 1).sum(), [a])
        self.assertTrue(ok, "\n".join(report))

    def test_swapaxes_grad(self):
        a = rt(2, 3, 4, seed=1)
        ok, report = gradcheck.check(lambda: (a.swapaxes(-2, -1) ** 2).sum(), [a])
        self.assertTrue(ok, "\n".join(report))

    def test_getitem_slice_grad(self):
        a = rt(2, 3, 6, seed=1)

        def f():
            return (a[:, :, 0:3] * a[:, :, 3:6]).sum()

        ok, report = gradcheck.check(f, [a])
        self.assertTrue(ok, "\n".join(report))

    def test_getitem_repeated_index_accumulates_grad(self):
        # np.add.at must be used (not plain indexed assignment) so repeated
        # indices correctly accumulate rather than overwrite.
        a = Tensor([1.0, 2.0, 3.0], requires_grad=True)
        out = (a[[0, 0, 1]]).sum()
        out.backward()
        np.testing.assert_allclose(a.grad, [2.0, 1.0, 0.0])


class TestReductions(unittest.TestCase):
    def test_sum_axis_grad(self):
        a = rt(3, 4, 5, seed=1)
        ok, report = gradcheck.check(lambda: a.sum(axis=1).sum(), [a])
        self.assertTrue(ok, "\n".join(report))

    def test_mean_axis_grad(self):
        a = rt(3, 4, 5, seed=1)
        ok, report = gradcheck.check(lambda: (a.mean(axis=(1, 2)) ** 2).sum(), [a])
        self.assertTrue(ok, "\n".join(report))

    def test_mean_value_correctness(self):
        a = Tensor([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        np.testing.assert_allclose(a.mean().data, 3.5)
        np.testing.assert_allclose(a.mean(axis=1).data, [2.0, 5.0])


class TestNonlinearities(unittest.TestCase):
    def test_exp_log_grad(self):
        a = rt(5, seed=1, offset=3.0)
        ok, report = gradcheck.check(lambda: a.exp().sum(), [a])
        self.assertTrue(ok, "\n".join(report))
        b = rt(5, seed=2, offset=3.0)
        ok, report = gradcheck.check(lambda: b.log().sum(), [b])
        self.assertTrue(ok, "\n".join(report))

    def test_tanh_relu_grad(self):
        a = rt(6, seed=1)
        ok, report = gradcheck.check(lambda: a.tanh().sum(), [a])
        self.assertTrue(ok, "\n".join(report))
        b = rt(6, seed=2)
        ok, report = gradcheck.check(lambda: (b.relu() ** 2).sum(), [b])
        self.assertTrue(ok, "\n".join(report))

    def test_gelu_grad_and_shape(self):
        a = rt(10, seed=1)
        ok, report = gradcheck.check(lambda: a.gelu().sum(), [a])
        self.assertTrue(ok, "\n".join(report))

    def test_gelu_matches_known_values(self):
        # GELU(0) = 0; GELU is monotonically increasing and roughly x for
        # large positive x, roughly 0 for very negative x.
        a = Tensor([0.0, 5.0, -5.0])
        y = a.gelu().data
        self.assertAlmostEqual(y[0], 0.0, places=6)
        self.assertAlmostEqual(y[1], 5.0, places=3)
        self.assertAlmostEqual(y[2], 0.0, places=3)

    def test_softmax_sums_to_one_and_grad(self):
        a = rt(3, 5, seed=1)
        s = a.softmax(axis=-1)
        np.testing.assert_allclose(s.data.sum(axis=-1), np.ones(3), atol=1e-10)
        ok, report = gradcheck.check(lambda: (a.softmax(axis=-1) ** 2).sum(), [a])
        self.assertTrue(ok, "\n".join(report))


class TestMaskedFillAndLayerNorm(unittest.TestCase):
    def test_masked_fill_grad_zero_at_masked_positions(self):
        a = Tensor(np.random.default_rng(0).standard_normal((4, 4)), requires_grad=True)
        mask = np.triu(np.ones((4, 4), dtype=bool), k=1)
        out = a.masked_fill(mask, -1e9)
        out.backward(np.ones((4, 4)))
        # masked positions must receive exactly zero gradient
        self.assertTrue(np.all(a.grad[mask] == 0.0))
        self.assertTrue(np.all(a.grad[~mask] == 1.0))

    def test_layernorm_output_is_normalized(self):
        a = Tensor(np.random.default_rng(0).standard_normal((5, 8)) * 10 + 3, requires_grad=True)
        gamma = Tensor(np.ones(8), requires_grad=True)
        beta = Tensor(np.zeros(8), requires_grad=True)
        out = a.layernorm(gamma, beta)
        np.testing.assert_allclose(out.data.mean(axis=-1), np.zeros(5), atol=1e-6)
        np.testing.assert_allclose(out.data.std(axis=-1), np.ones(5), atol=1e-5)

    def test_layernorm_grad(self):
        a = rt(4, 6, seed=1)
        g = rt(6, seed=2)
        b = rt(6, seed=3)
        ok, report = gradcheck.check(lambda: (a.layernorm(g, b) ** 2).sum(), [a, g, b])
        self.assertTrue(ok, "\n".join(report))


class TestCrossEntropyAndEmbedding(unittest.TestCase):
    def test_cross_entropy_grad(self):
        logits = rt(2, 3, 7, seed=1)
        targets = np.random.default_rng(0).integers(0, 7, size=(2, 3))
        ok, report = gradcheck.check(lambda: logits.cross_entropy(targets), [logits])
        self.assertTrue(ok, "\n".join(report))

    def test_cross_entropy_matches_hand_computation(self):
        logits = Tensor([[2.0, 1.0, 0.0]])
        loss = logits.cross_entropy(np.array([0]))
        e = np.exp([2.0, 1.0, 0.0])
        expected = -np.log(e[0] / e.sum())
        self.assertAlmostEqual(float(loss.data), expected, places=6)

    def test_embedding_grad_with_repeats(self):
        w = rt(6, 4, seed=1)
        idx = np.array([0, 0, 2, 5])
        ok, report = gradcheck.check(lambda: embedding(w, idx).sum(), [w])
        self.assertTrue(ok, "\n".join(report))

    def test_embedding_forward_correctness(self):
        w = Tensor([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        out = embedding(w, np.array([2, 0]))
        np.testing.assert_allclose(out.data, [[5.0, 6.0], [1.0, 2.0]])


class TestBackwardMechanics(unittest.TestCase):
    def test_diamond_shared_subexpression_accumulates_grad(self):
        # x used twice: grad must accumulate from both paths, not overwrite.
        x = Tensor([2.0], requires_grad=True)
        y = ((x * x) + (x * 3.0)).sum()  # dy/dx = 2x + 3 = 7
        y.backward()
        np.testing.assert_allclose(x.grad, [7.0])

    def test_backward_requires_scalar_without_explicit_grad(self):
        a = Tensor([1.0, 2.0], requires_grad=True)
        with self.assertRaises(ValueError):
            a.backward()

    def test_zero_grad_clears(self):
        a = Tensor([1.0], requires_grad=True)
        (a * 2).sum().backward()
        self.assertIsNotNone(a.grad)
        a.zero_grad()
        self.assertIsNone(a.grad)


if __name__ == "__main__":
    unittest.main()
