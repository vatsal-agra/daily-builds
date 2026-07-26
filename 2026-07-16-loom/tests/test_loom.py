"""Unit test suite for Loom. Run with: python3 -m unittest tests.test_loom -v"""
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom.tensor import Tensor, embedding, gather_rows, softmax, layer_norm, gelu, cross_entropy
from loom.tokenizer import BPETokenizer
from loom.model import GPT
from loom.train import get_batch, min_tokens_required, train, save_checkpoint, load_checkpoint
from loom.generate import generate
from loom import gradcheck as gradcheck_mod


CORPUS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "corpus.txt")


class TestTensorOps(unittest.TestCase):
    def test_add_mul_known_values(self):
        a = Tensor([[1.0, 2.0], [3.0, 4.0]], requires_grad=True)
        b = Tensor([[5.0, 6.0], [7.0, 8.0]], requires_grad=True)
        c = (a * b).sum()
        c.backward()
        np.testing.assert_allclose(a.grad, b.data)
        np.testing.assert_allclose(b.grad, a.data)

    def test_matmul_shapes(self):
        a = Tensor(np.random.randn(2, 3, 4), requires_grad=True)
        b = Tensor(np.random.randn(4, 5), requires_grad=True)
        out = a @ b
        self.assertEqual(out.shape, (2, 3, 5))
        out.sum().backward()
        self.assertEqual(a.grad.shape, a.data.shape)
        self.assertEqual(b.grad.shape, b.data.shape)

    def test_softmax_sums_to_one(self):
        x = Tensor(np.random.randn(4, 7))
        p = softmax(x, axis=-1)
        np.testing.assert_allclose(p.data.sum(axis=-1), np.ones(4), atol=1e-10)

    def test_softmax_backward_shape(self):
        x = Tensor(np.random.randn(3, 5), requires_grad=True)
        out = softmax(x, axis=-1).sum()
        out.backward()
        self.assertEqual(x.grad.shape, (3, 5))

    def test_layer_norm_zero_mean_unit_var(self):
        x = Tensor(np.random.randn(5, 8) * 10 + 3)
        gamma = Tensor(np.ones(8))
        beta = Tensor(np.zeros(8))
        y = layer_norm(x, gamma, beta).data
        np.testing.assert_allclose(y.mean(axis=-1), np.zeros(5), atol=1e-6)
        np.testing.assert_allclose(y.std(axis=-1), np.ones(5), atol=1e-3)

    def test_gelu_matches_reference(self):
        x = Tensor([0.0, 1.0, -1.0])
        y = gelu(x).data
        c = (2.0 / np.pi) ** 0.5
        expected = 0.5 * x.data * (1 + np.tanh(c * (x.data + 0.044715 * x.data ** 3)))
        np.testing.assert_allclose(y, expected, atol=1e-12)

    def test_embedding_gather_and_scatter_grad(self):
        w = Tensor(np.arange(12, dtype=np.float64).reshape(4, 3), requires_grad=True)
        idx = np.array([0, 0, 2])
        out = embedding(w, idx)
        np.testing.assert_allclose(out.data, w.data[idx])
        out.sum().backward()
        expected_grad = np.zeros((4, 3))
        expected_grad[0] += 1
        expected_grad[0] += 1
        expected_grad[2] += 1
        np.testing.assert_allclose(w.grad, expected_grad)

    def test_cross_entropy_matches_manual(self):
        logits = Tensor([[1.0, 2.0, 0.5], [0.1, 0.1, 0.1]])
        targets = np.array([1, 2])
        loss = cross_entropy(logits, targets)
        probs = np.exp(logits.data) / np.exp(logits.data).sum(axis=-1, keepdims=True)
        expected = -np.log(probs[np.arange(2), targets]).mean()
        self.assertAlmostEqual(float(loss.data), expected, places=10)

    def test_shape_is_derived_not_stale(self):
        t = Tensor(np.zeros((2, 3)))
        self.assertEqual(t.shape, (2, 3))
        t.data = np.zeros((5, 5))
        self.assertEqual(t.shape, (5, 5))  # property, always fresh

    def test_gradcheck_suite_passes(self):
        self.assertTrue(gradcheck_mod.run_all(verbose=False))


class TestTokenizer(unittest.TestCase):
    def test_roundtrip_ascii(self):
        tok = BPETokenizer()
        text = "the quick brown fox jumps over the lazy dog. " * 5
        tok.train(text, vocab_size=280)
        ids = tok.encode(text)
        self.assertEqual(tok.decode(ids), text)

    def test_roundtrip_unicode_and_punctuation(self):
        tok = BPETokenizer()
        text = "Hello, world! Café naïve — emoji: \U0001F600 done."
        tok.train(text, vocab_size=260)
        ids = tok.encode(text)
        self.assertEqual(tok.decode(ids), text)

    def test_roundtrip_empty_string(self):
        tok = BPETokenizer()
        tok.train("some training text here " * 3, vocab_size=260)
        self.assertEqual(tok.encode(""), [])
        self.assertEqual(tok.decode([]), "")

    def test_vocab_size_never_exceeds_requested(self):
        tok = BPETokenizer()
        tok.train("a a a b b c", vocab_size=270)
        self.assertLessEqual(tok.vocab_size, 270)

    def test_save_load_roundtrip(self):
        tok = BPETokenizer()
        tok.train("the quick brown fox " * 10, vocab_size=270)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tok.json")
            tok.save(path)
            reloaded = BPETokenizer.load(path)
        self.assertEqual(tok.merges, reloaded.merges)
        text = "the quick fox"
        self.assertEqual(tok.encode(text), reloaded.encode(text))

    def test_rejects_vocab_size_below_256(self):
        tok = BPETokenizer()
        with self.assertRaises(ValueError):
            tok.train("hello", vocab_size=100)


class TestModel(unittest.TestCase):
    def test_forward_shape(self):
        model = GPT(vocab_size=50, d_model=16, n_layer=2, n_head=2, block_size=10, seed=0)
        idx = np.random.randint(0, 50, size=(3, 7))
        logits = model(idx)
        self.assertEqual(logits.shape, (3, 7, 50))

    def test_rejects_sequence_longer_than_block_size(self):
        model = GPT(vocab_size=50, d_model=16, n_layer=1, n_head=2, block_size=4, seed=0)
        idx = np.random.randint(0, 50, size=(1, 5))
        with self.assertRaises(ValueError):
            model(idx)

    def test_same_seed_gives_identical_init(self):
        a = GPT(vocab_size=30, d_model=8, n_layer=1, n_head=2, block_size=8, seed=42)
        b = GPT(vocab_size=30, d_model=8, n_layer=1, n_head=2, block_size=8, seed=42)
        for p1, p2 in zip(a.parameters(), b.parameters()):
            np.testing.assert_array_equal(p1.data, p2.data)

    def test_different_seed_gives_different_init(self):
        a = GPT(vocab_size=30, d_model=8, n_layer=1, n_head=2, block_size=8, seed=1)
        b = GPT(vocab_size=30, d_model=8, n_layer=1, n_head=2, block_size=8, seed=2)
        differs = any(not np.array_equal(p1.data, p2.data)
                      for p1, p2 in zip(a.parameters(), b.parameters()))
        self.assertTrue(differs)

    def test_no_causal_leakage(self):
        model = GPT(vocab_size=50, d_model=16, n_layer=2, n_head=2, block_size=8, seed=0)
        x1 = np.array([[1, 2, 3, 4, 5]])
        x2 = x1.copy()
        x2[0, -1] = 49
        out1 = model(x1).data
        out2 = model(x2).data
        np.testing.assert_allclose(out1[0, :4], out2[0, :4], atol=1e-12)
        self.assertGreater(np.abs(out1[0, 4] - out2[0, 4]).max(), 1e-6)

    def test_attention_rows_sum_to_one_and_causal(self):
        model = GPT(vocab_size=20, d_model=8, n_layer=1, n_head=2, block_size=6, seed=0)
        idx = np.array([[1, 2, 3, 4]])
        model(idx, capture_attn=True)
        attn = model.attention_maps()[0][0]  # (n_head, T, T)
        row_sums = attn.sum(axis=-1)
        np.testing.assert_allclose(row_sums, np.ones_like(row_sums), atol=1e-8)
        for h in range(attn.shape[0]):
            for q in range(4):
                for k in range(q + 1, 4):
                    self.assertAlmostEqual(attn[h, q, k], 0.0, places=8)


class TestTraining(unittest.TestCase):
    def test_get_batch_shapes(self):
        ids = np.arange(200)
        rng = np.random.default_rng(0)
        x, y = get_batch(ids, block_size=16, batch_size=4, rng=rng)
        self.assertEqual(x.shape, (4, 16))
        self.assertEqual(y.shape, (4, 16))
        np.testing.assert_array_equal(x[:, 1:], y[:, :-1])

    def test_get_batch_rejects_too_short_corpus(self):
        ids = np.arange(65)  # exactly block_size + 1, one short of what's needed
        rng = np.random.default_rng(0)
        with self.assertRaises(ValueError):
            get_batch(ids, block_size=64, batch_size=4, rng=rng)

    def test_get_batch_accepts_minimum_length(self):
        ids = np.arange(min_tokens_required(block_size=8))
        rng = np.random.default_rng(0)
        x, y = get_batch(ids, block_size=8, batch_size=2, rng=rng)
        self.assertEqual(x.shape, (2, 8))

    def test_loss_decreases_over_training(self):
        with open(CORPUS_PATH, encoding="utf-8") as f:
            text = f.read()
        tok = BPETokenizer()
        tok.train(text, vocab_size=280)
        ids = np.array(tok.encode(text), dtype=np.int64)
        model = GPT(vocab_size=tok.vocab_size, d_model=16, n_layer=2, n_head=2,
                    block_size=32, seed=0)
        history = train(model, ids, steps=40, batch_size=8, base_lr=5e-3, seed=0, log_every=10)
        self.assertLess(history[-1][1], history[0][1])

    def test_checkpoint_roundtrip(self):
        model = GPT(vocab_size=30, d_model=8, n_layer=1, n_head=2, block_size=8, seed=3)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ckpt.npz")
            save_checkpoint(path, model)
            reloaded = load_checkpoint(path)
        self.assertEqual(reloaded.config(), model.config())
        for p1, p2 in zip(model.parameters(), reloaded.parameters()):
            np.testing.assert_array_equal(p1.data, p2.data)
        idx = np.array([[1, 2, 3]])
        np.testing.assert_allclose(model(idx).data, reloaded(idx).data)


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self.model = GPT(vocab_size=40, d_model=16, n_layer=2, n_head=2, block_size=16, seed=0)

    def test_greedy_is_deterministic(self):
        out1 = generate(self.model, [1, 2, 3], max_new_tokens=10, temperature=0.0)
        out2 = generate(self.model, [1, 2, 3], max_new_tokens=10, temperature=0.0)
        self.assertEqual(out1, out2)

    def test_ids_stay_in_vocab_range(self):
        out = generate(self.model, [1, 2, 3], max_new_tokens=30, temperature=1.0,
                        top_k=10, rng=np.random.default_rng(0))
        self.assertTrue(all(0 <= i < 40 for i in out))

    def test_same_seed_same_sample(self):
        out1 = generate(self.model, [1, 2, 3], max_new_tokens=15, temperature=0.9,
                         top_p=0.9, rng=np.random.default_rng(7))
        out2 = generate(self.model, [1, 2, 3], max_new_tokens=15, temperature=0.9,
                         top_p=0.9, rng=np.random.default_rng(7))
        self.assertEqual(out1, out2)

    def test_rejects_empty_prompt(self):
        with self.assertRaises(ValueError):
            generate(self.model, [], max_new_tokens=5)

    def test_context_window_slides_past_block_size(self):
        out = generate(self.model, [1, 2, 3], max_new_tokens=40, temperature=0.0)
        self.assertEqual(len(out), 43)


if __name__ == "__main__":
    unittest.main()
