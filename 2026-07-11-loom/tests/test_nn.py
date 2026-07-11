import unittest

import numpy as np

from loom import gradcheck
from loom.nn import GPT, Block, CausalSelfAttention, LayerNorm, Linear, MLP
from loom.tensor import Tensor


class TestLinearLayerNorm(unittest.TestCase):
    def test_linear_grad(self):
        rng = np.random.default_rng(0)
        lin = Linear(5, 3, rng)
        x = Tensor(rng.standard_normal((2, 5)), requires_grad=True)
        params = [x] + lin.parameters()
        ok, report = gradcheck.check(lambda: lin(x).sum(), params)
        self.assertTrue(ok, "\n".join(report))

    def test_layernorm_module_grad(self):
        ln = LayerNorm(6)
        x = Tensor(np.random.default_rng(0).standard_normal((3, 6)), requires_grad=True)
        params = [x] + ln.parameters()
        ok, report = gradcheck.check(lambda: (ln(x) ** 2).sum(), params)
        self.assertTrue(ok, "\n".join(report))


class TestAttention(unittest.TestCase):
    def test_causal_attention_grad(self):
        rng = np.random.default_rng(0)
        attn = CausalSelfAttention(n_embd=8, n_head=2, rng=rng)
        x = Tensor(rng.standard_normal((2, 5, 8)), requires_grad=True)
        params = [x] + attn.parameters()
        ok, report = gradcheck.check(lambda: attn(x).sum(), params, tol=2e-3)
        self.assertTrue(ok, "\n".join(report))

    def test_causal_mask_blocks_future_information(self):
        """The defining correctness property of causal attention: the output
        at position t must be identical regardless of what tokens appear
        after position t in the input. This is a functional check, distinct
        from (and complementary to) the gradient checks above."""
        rng = np.random.default_rng(0)
        n_embd, n_head, T = 8, 2, 6
        model = GPT(vocab_size=20, block_size=T, n_embd=n_embd, n_head=n_head, n_layer=2, seed=1)

        idx_a = rng.integers(0, 20, size=(1, T))
        idx_b = idx_a.copy()
        idx_b[0, 3:] = rng.integers(0, 20, size=T - 3)  # change everything after position 2

        logits_a = model.forward(idx_a).data
        logits_b = model.forward(idx_b).data
        # positions 0, 1, 2 only saw identical tokens (0..2) in both runs
        np.testing.assert_allclose(logits_a[0, :3], logits_b[0, :3], atol=1e-9)
        # position 3 onward legitimately differs (its own token changed)
        self.assertFalse(np.allclose(logits_a[0, 3], logits_b[0, 3]))

    def test_attention_weights_sum_to_one_per_row(self):
        rng = np.random.default_rng(0)
        model = GPT(vocab_size=15, block_size=6, n_embd=8, n_head=2, n_layer=2, seed=0)
        idx = rng.integers(0, 15, size=(1, 6))
        model.forward(idx, capture_attn=True)
        for layer_att in model._last_attn:
            # (B, nh, T, T) -> rows sum to 1
            np.testing.assert_allclose(layer_att.sum(axis=-1), np.ones(layer_att.shape[:-1]), atol=1e-6)

    def test_return_attn_matches_normal_forward(self):
        """Regression: CausalSelfAttention/Block's return_attn=True path must
        compute the exact same output as the normal path (they used to be
        two independently hand-written implementations -- see REVIEW.md
        finding #7)."""
        rng = np.random.default_rng(0)
        block = Block(n_embd=8, n_head=2, rng=rng)
        x_data = rng.standard_normal((2, 5, 8))
        out_normal = block(Tensor(x_data)).data
        out_attn, att = block(Tensor(x_data), return_attn=True)
        np.testing.assert_allclose(out_normal, out_attn.data, atol=1e-12)
        self.assertEqual(att.shape, (2, 2, 5, 5))


class TestMLPBlock(unittest.TestCase):
    def test_mlp_grad(self):
        rng = np.random.default_rng(0)
        mlp = MLP(8, rng)
        x = Tensor(rng.standard_normal((2, 8)), requires_grad=True)
        ok, report = gradcheck.check(lambda: mlp(x).sum(), [x] + mlp.parameters())
        self.assertTrue(ok, "\n".join(report))

    def test_block_grad(self):
        rng = np.random.default_rng(0)
        block = Block(8, 2, rng)
        x = Tensor(rng.standard_normal((2, 4, 8)), requires_grad=True)
        ok, report = gradcheck.check(lambda: block(x).sum(), [x] + block.parameters(), tol=2e-3)
        self.assertTrue(ok, "\n".join(report))


class TestGPT(unittest.TestCase):
    def test_full_model_grad_end_to_end(self):
        rng = np.random.default_rng(0)
        model = GPT(vocab_size=11, block_size=5, n_embd=8, n_head=2, n_layer=2, seed=1)
        idx = rng.integers(0, 11, size=(2, 5))
        targets = rng.integers(0, 11, size=(2, 5))

        def f():
            _, loss = model(idx, targets)
            return loss

        ok, report = gradcheck.check(f, model.parameters(), tol=2e-3)
        self.assertTrue(ok, "\n".join(report))

    def test_logits_shape(self):
        model = GPT(vocab_size=13, block_size=7, n_embd=8, n_head=2, n_layer=1, seed=0)
        idx = np.zeros((3, 4), dtype=int)
        logits = model.forward(idx)
        self.assertEqual(logits.shape, (3, 4, 13))

    def test_rejects_mismatched_n_embd_n_head(self):
        with self.assertRaises(ValueError):
            GPT(vocab_size=10, block_size=5, n_embd=8, n_head=3, n_layer=1)

    def test_rejects_sequence_longer_than_block_size(self):
        model = GPT(vocab_size=10, block_size=4, n_embd=8, n_head=2, n_layer=1, seed=0)
        with self.assertRaises(ValueError):
            model.forward(np.zeros((1, 5), dtype=int))

    def test_rejects_out_of_range_token_id(self):
        model = GPT(vocab_size=10, block_size=4, n_embd=8, n_head=2, n_layer=1, seed=0)
        with self.assertRaises(ValueError):
            model.forward(np.array([[1, 2, 10]]))
        with self.assertRaises(ValueError):
            model.forward(np.array([[1, -1, 2]]))

    def test_weight_tying(self):
        model = GPT(vocab_size=10, block_size=4, n_embd=8, n_head=2, n_layer=1, seed=0)
        # the output head must literally be the token embedding, transposed
        self.assertIs(model.tok_emb.weight, model.parameters()[0])
        idx = np.zeros((1, 4), dtype=int)
        logits = model.forward(idx)
        # Perturbing the (shared) embedding weight must change the output
        # logits. Note: a perfectly *uniform* constant shift would NOT do
        # so here -- ln_f's zero-mean normalization combined with the tied
        # output projection makes any pure constant offset to every
        # embedding row provably invisible in the logits. Use per-element
        # random noise instead, which isn't a constant shift.
        noise = np.random.default_rng(0).standard_normal(model.tok_emb.weight.data.shape) * 0.1
        model.tok_emb.weight.data = model.tok_emb.weight.data + noise
        logits2 = model.forward(idx)
        self.assertFalse(np.allclose(logits.data, logits2.data))


if __name__ == "__main__":
    unittest.main()
