import unittest
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loom.nn import GPT, cross_entropy_loss, MultiHeadAttention, causal_mask, dropout
from loom.tensor import Tensor


class TestModelShapes(unittest.TestCase):
    def setUp(self):
        np.random.seed(0)
        self.vocab = 10
        self.model = GPT(vocab_size=self.vocab, d_model=16, n_heads=4, n_layers=2, d_ff=32, max_seq_len=8)

    def test_forward_shape(self):
        idx = np.random.randint(0, self.vocab, size=(3, 5))
        logits = self.model(idx)
        self.assertEqual(logits.shape, (3, 5, self.vocab))

    def test_forward_rejects_too_long_sequence(self):
        idx = np.random.randint(0, self.vocab, size=(1, 9))
        with self.assertRaises(ValueError):
            self.model(idx)

    def test_all_params_get_gradients(self):
        idx = np.random.randint(0, self.vocab, size=(2, 4))
        targets = np.random.randint(0, self.vocab, size=(2, 4))
        loss = cross_entropy_loss(self.model(idx), targets)
        loss.backward()
        for p in self.model.params():
            self.assertIsNotNone(p.grad)
            self.assertEqual(p.grad.shape, p.data.shape)
            self.assertFalse(np.any(np.isnan(p.grad)))

    def test_loss_is_positive_finite_scalar(self):
        idx = np.random.randint(0, self.vocab, size=(2, 4))
        targets = np.random.randint(0, self.vocab, size=(2, 4))
        loss = cross_entropy_loss(self.model(idx), targets)
        self.assertEqual(loss.data.shape, ())
        self.assertTrue(np.isfinite(loss.item()))
        self.assertGreater(loss.item(), 0)

    def test_causal_mask_blocks_future(self):
        attn = MultiHeadAttention(d_model=8, n_heads=2)
        x = Tensor(np.random.randn(1, 4, 8), requires_grad=True)
        mask = causal_mask(4)
        _, weights = attn(x, mask)
        w = weights.data[0]  # (H,T,T)
        upper = np.triu_indices(4, k=1)
        for h in range(w.shape[0]):
            np.testing.assert_allclose(w[h][upper], 0.0, atol=1e-9)

    def test_attention_rows_sum_to_one(self):
        attn = MultiHeadAttention(d_model=8, n_heads=2)
        x = Tensor(np.random.randn(1, 5, 8))
        mask = causal_mask(5)
        _, weights = attn(x, mask)
        np.testing.assert_allclose(weights.data.sum(axis=-1), np.ones((1, 2, 5)), atol=1e-6)

    def test_dropout_disabled_at_eval_is_identity(self):
        x = Tensor(np.random.randn(4, 4))
        out = dropout(x, p=0.5, training=False)
        np.testing.assert_array_equal(out.data, x.data)

    def test_dropout_zeroes_and_scales_at_train(self):
        np.random.seed(0)
        x = Tensor(np.ones((200, 200)), requires_grad=True)
        out = dropout(x, p=0.3, training=True)
        zero_frac = np.mean(out.data == 0)
        self.assertAlmostEqual(zero_frac, 0.3, delta=0.05)
        nonzero = out.data[out.data != 0]
        np.testing.assert_allclose(nonzero, 1.0 / 0.7, atol=1e-8)

    def test_dropout_gradient_flows_through_surviving_units(self):
        x = Tensor(np.ones(50), requires_grad=True)
        out = dropout(x, p=0.4, training=True)
        out.sum().backward()
        # gradient at each position is either 0 (dropped) or 1/(1-p) (kept)
        self.assertTrue(np.all((x.grad == 0) | np.isclose(x.grad, 1 / 0.6)))

    def test_model_forward_matches_between_calls_when_dropout_zero(self):
        model = GPT(vocab_size=6, d_model=8, n_heads=2, n_layers=1, d_ff=8, max_seq_len=4, dropout_p=0.0)
        idx = np.array([[1, 2, 3]])
        a = model(idx, training=True).data.copy()
        b = model(idx, training=True).data.copy()
        np.testing.assert_allclose(a, b)

    def test_end_to_end_gradient_check(self):
        """Perturb real weights inside a real forward pass; compare analytic
        vs numeric gradient (the same check performed manually while building
        this model — kept here as a permanent regression test)."""
        model = GPT(vocab_size=5, d_model=8, n_heads=2, n_layers=2, d_ff=12, max_seq_len=4)
        idx = np.random.randint(0, 5, size=(2, 3))
        targets = np.random.randint(0, 5, size=(2, 3))

        def loss_fn():
            return cross_entropy_loss(model(idx), targets)

        probe = model.blocks[0].attn.q_proj.W
        for p in model.params():
            p.grad = None
        loss = loss_fn()
        loss.backward()
        analytic = probe.grad.copy()

        h = 1e-5
        flat = probe.data.reshape(-1)
        ag = analytic.reshape(-1)
        for i in [0, flat.size // 2, flat.size - 1]:
            orig = flat[i]
            flat[i] = orig + h
            lp = loss_fn().item()
            flat[i] = orig - h
            lm = loss_fn().item()
            flat[i] = orig
            numeric = (lp - lm) / (2 * h)
            rel = abs(ag[i] - numeric) / (abs(ag[i]) + abs(numeric) + 1e-8)
            self.assertLess(rel, 1e-2, f"index {i}: analytic={ag[i]} numeric={numeric}")


if __name__ == "__main__":
    unittest.main()
