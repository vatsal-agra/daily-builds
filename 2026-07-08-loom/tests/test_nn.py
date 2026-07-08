import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from loom.nn import GPT, CausalSelfAttention, LayerNorm, MLP, gelu  # noqa: E402
from loom.tensor import Tensor, no_grad  # noqa: E402

np.random.seed(1)


def make_gpt(vocab=17, n_embd=16, n_head=4, n_layer=2, block_size=10):
    return GPT(vocab, n_embd, n_head, n_layer, block_size)


class TestLayerNorm(unittest.TestCase):
    def test_normalizes_to_zero_mean_unit_var(self):
        ln = LayerNorm(8)
        x = Tensor(np.random.randn(3, 8) * 5 + 2, requires_grad=True)
        out = ln(x)
        mu = out.data.mean(axis=-1)
        var = out.data.var(axis=-1)
        self.assertTrue(np.allclose(mu, 0, atol=1e-6))
        self.assertTrue(np.allclose(var, 1, atol=1e-4))

    def test_backward_runs(self):
        ln = LayerNorm(4)
        x = Tensor(np.random.randn(2, 4), requires_grad=True)
        out = ln(x)
        out.sum().backward()
        self.assertIsNotNone(x.grad)
        self.assertIsNotNone(ln.gamma.grad)
        self.assertIsNotNone(ln.beta.grad)


class TestGelu(unittest.TestCase):
    def test_matches_reference_within_tolerance(self):
        x = np.linspace(-3, 3, 25)
        t = Tensor(x)
        out = gelu(t).data
        # reference: exact GELU via erf
        import math

        ref = np.array([xi * 0.5 * (1 + math.erf(xi / math.sqrt(2))) for xi in x])
        self.assertTrue(np.allclose(out, ref, atol=1e-3))


class TestCausalAttention(unittest.TestCase):
    def test_future_token_never_affects_past_output(self):
        attn = CausalSelfAttention(n_embd=8, n_head=2, block_size=6)
        B, T = 1, 5
        x1 = np.random.randn(B, T, 8)
        x2 = x1.copy()
        x2[:, -1, :] = np.random.randn(8) * 100  # perturb only the LAST token

        with no_grad():
            out1, _ = attn(Tensor(x1))
            out2, _ = attn(Tensor(x2))
        # every position except the last must be bit-for-bit identical
        self.assertTrue(np.allclose(out1.data[:, :-1, :], out2.data[:, :-1, :]))
        # sanity: the last position's output SHOULD differ (attn is not a no-op)
        self.assertFalse(np.allclose(out1.data[:, -1, :], out2.data[:, -1, :]))

    def test_middle_perturbation_only_affects_itself_and_later(self):
        attn = CausalSelfAttention(n_embd=8, n_head=2, block_size=6)
        B, T = 1, 5
        x1 = np.random.randn(B, T, 8)
        x2 = x1.copy()
        x2[:, 2, :] = np.random.randn(8) * 100  # perturb position 2

        with no_grad():
            out1, _ = attn(Tensor(x1))
            out2, _ = attn(Tensor(x2))
        self.assertTrue(np.allclose(out1.data[:, :2, :], out2.data[:, :2, :]))


class TestGPTForward(unittest.TestCase):
    def test_output_shape(self):
        model = make_gpt()
        idx = np.random.randint(0, 17, size=(3, 7))
        logits, loss = model(idx)
        self.assertEqual(logits.shape, (3, 7, 17))
        self.assertIsNone(loss)

    def test_loss_is_finite_and_scalar(self):
        model = make_gpt()
        idx = np.random.randint(0, 17, size=(2, 6))
        targets = np.random.randint(0, 17, size=(2, 6))
        logits, loss = model(idx, targets=targets)
        self.assertEqual(loss.data.shape, ())
        self.assertTrue(np.isfinite(loss.item()))

    def test_backward_populates_all_param_grads(self):
        model = make_gpt()
        idx = np.random.randint(0, 17, size=(2, 6))
        targets = np.random.randint(0, 17, size=(2, 6))
        _, loss = model(idx, targets=targets)
        for p in model.parameters():
            p.zero_grad()
        loss.backward()
        for name, p in model.named_parameters():
            self.assertIsNotNone(p.grad, f"{name} has no gradient")
            self.assertTrue(np.isfinite(p.grad).all(), f"{name} has non-finite gradient")

    def test_kv_cache_matches_full_forward(self):
        model = make_gpt(block_size=12)
        prompt = np.random.randint(0, 17, size=(1, 4))
        with no_grad():
            full_logits, _ = model(prompt)
            first_tok = int(np.argmax(full_logits.data[0, -1]))
            extended = np.concatenate([prompt, [[first_tok]]], axis=1)
            full_logits2, _ = model(extended)

            kv_caches = model.new_kv_caches()
            cached_logits, _ = model(prompt, kv_caches=kv_caches)
            cached_next, _ = model(np.array([[first_tok]]), kv_caches=kv_caches)

        self.assertTrue(np.allclose(full_logits.data, cached_logits.data, atol=1e-8))
        self.assertTrue(
            np.allclose(full_logits2.data[:, -1, :], cached_next.data[:, -1, :], atol=1e-6)
        )

    def test_generate_respects_block_size(self):
        model = make_gpt(block_size=8)
        prompt = np.random.randint(0, 17, size=(1, 6))
        with self.assertWarns(RuntimeWarning):
            out = model.generate(prompt, max_new_tokens=20, use_kv_cache=True)
        self.assertLessEqual(out.shape[1], 8)

    def test_generate_warns_when_prompt_already_exceeds_block_size(self):
        model = make_gpt(block_size=8)
        prompt = np.random.randint(0, 17, size=(1, 12))  # already over block_size
        with self.assertWarns(RuntimeWarning):
            out = model.generate(prompt, max_new_tokens=5, use_kv_cache=True)
        self.assertEqual(out.shape, (1, 12))  # 0 new tokens, prompt returned unchanged

    def test_generate_no_warning_when_kv_cache_disabled(self):
        import warnings

        model = make_gpt(block_size=8)
        prompt = np.random.randint(0, 17, size=(1, 12))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            out = model.generate(prompt, max_new_tokens=5, use_kv_cache=False)
        self.assertEqual(out.shape, (1, 17))

    def test_generate_without_cache_matches_shape(self):
        model = make_gpt(block_size=8)
        prompt = np.random.randint(0, 17, size=(1, 3))
        out = model.generate(prompt, max_new_tokens=10, use_kv_cache=False)
        self.assertEqual(out.shape, (1, 13))


if __name__ == "__main__":
    unittest.main()
