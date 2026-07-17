import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tokenizer import BPETokenizer  # noqa: E402
from nn import GPT, cross_entropy_loss, softmax  # noqa: E402
from optim import Adam  # noqa: E402
from generate import sample, filter_logits  # noqa: E402
import train as train_mod  # noqa: E402


class TestTokenizer(unittest.TestCase):
    def setUp(self):
        self.text = (
            "the quick brown fox jumps over the lazy dog. "
            "the dog barks at the fox and the fox runs away. "
        ) * 30
        self.tok = BPETokenizer()
        self.tok.train(self.text, vocab_size=280)

    def test_round_trip(self):
        self.assertEqual(self.tok.decode(self.tok.encode(self.text)), self.text)

    def test_compresses(self):
        ids = self.tok.encode(self.text)
        self.assertLess(len(ids), len(self.text.encode("utf-8")))

    def test_unicode_round_trip(self):
        s = "héllo wörld 🚀 日本語 — em dash, “curly quotes”"
        self.assertEqual(self.tok.decode(self.tok.encode(s)), s)

    def test_empty_string(self):
        self.assertEqual(self.tok.encode(""), [])
        self.assertEqual(self.tok.decode([]), "")

    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tok.json")
            self.tok.save(path)
            loaded = BPETokenizer.load(path)
            ids = self.tok.encode("the quick fox")
            self.assertEqual(loaded.encode("the quick fox"), ids)
            self.assertEqual(loaded.decode(ids), self.tok.decode(ids))

    def test_min_vocab_size_enforced(self):
        with self.assertRaises(ValueError):
            BPETokenizer().train("hello", vocab_size=100)

    def test_unseen_bytes_still_encode(self):
        # a character that never appeared during BPE training must still
        # round-trip, since byte-level BPE always falls back to raw bytes
        s = "☃ snowman never seen in training"
        self.assertEqual(self.tok.decode(self.tok.encode(s)), s)


class TestNN(unittest.TestCase):
    def test_softmax_sums_to_one(self):
        x = np.random.randn(3, 5)
        p = softmax(x, axis=-1)
        np.testing.assert_allclose(p.sum(axis=-1), np.ones(3), atol=1e-8)

    def test_causal_mask_blocks_future(self):
        model = GPT(vocab_size=20, block_size=8, n_layer=1, n_head=2, n_embd=8)
        idx = np.array([[1, 2, 3, 4]])
        model.forward(idx)
        attn = model.blocks[0].attn._cache[3][0]  # (H, T, T)
        # every head must assign ~0 weight to any key position after the query
        upper = np.triu_indices(attn.shape[-1], k=1)
        for h in range(attn.shape[0]):
            self.assertTrue(np.allclose(attn[h][upper], 0.0, atol=1e-9))

    def test_forward_rejects_overlong_sequence(self):
        model = GPT(vocab_size=20, block_size=4, n_layer=1, n_head=1, n_embd=4)
        with self.assertRaises(AssertionError):
            model.forward(np.array([[1, 2, 3, 4, 5]]))

    def test_cross_entropy_gradient_shape_and_sign(self):
        logits = np.random.randn(2, 3, 10)
        targets = np.array([[1, 2, 3], [4, 5, 6]])
        loss, dlogits = cross_entropy_loss(logits, targets)
        self.assertGreater(loss, 0)
        self.assertEqual(dlogits.shape, logits.shape)

    def test_forward_backward_no_nan(self):
        model = GPT(vocab_size=30, block_size=10, n_layer=2, n_head=2, n_embd=16)
        idx = np.random.randint(0, 30, size=(4, 10))
        targets = np.random.randint(0, 30, size=(4, 10))
        model.zero_grad()
        logits = model.forward(idx)
        loss, dlogits = cross_entropy_loss(logits, targets)
        model.backward(dlogits)
        self.assertFalse(np.isnan(loss))
        for name, p, g in model.parameters():
            self.assertFalse(np.isnan(g).any(), f"NaN grad in {name}")


class TestOptim(unittest.TestCase):
    def test_adam_reduces_quadratic_loss(self):
        model = GPT(vocab_size=15, block_size=6, n_layer=1, n_head=1, n_embd=8)
        opt = Adam(model, lr=1e-2)
        idx = np.random.randint(0, 15, size=(4, 6))
        targets = np.random.randint(0, 15, size=(4, 6))

        def step_loss():
            model.zero_grad()
            logits = model.forward(idx)
            loss, dlogits = cross_entropy_loss(logits, targets)
            model.backward(dlogits)
            opt.step()
            return loss

        losses = [step_loss() for _ in range(60)]
        self.assertLess(losses[-1], losses[0])


class TestGenerate(unittest.TestCase):
    def setUp(self):
        text = "the fox ran to the river. the fox ran home again. " * 20
        self.tok = BPETokenizer()
        self.tok.train(text, vocab_size=270)
        self.model = GPT(vocab_size=self.tok.vocab_size, block_size=16, n_layer=1, n_head=2, n_embd=8)

    def test_greedy_is_deterministic(self):
        rng1 = np.random.default_rng(0)
        rng2 = np.random.default_rng(0)
        out1 = sample(self.model, self.tok, prompt="the fox", max_new_tokens=10, temperature=0.0, rng=rng1)
        out2 = sample(self.model, self.tok, prompt="the fox", max_new_tokens=10, temperature=0.0, rng=rng2)
        self.assertEqual(out1, out2)

    def test_empty_prompt_does_not_crash(self):
        rng = np.random.default_rng(0)
        out = sample(self.model, self.tok, prompt="", max_new_tokens=5, rng=rng)
        self.assertIsInstance(out, str)

    def test_top_k_larger_than_vocab_does_not_crash(self):
        rng = np.random.default_rng(0)
        out = sample(self.model, self.tok, prompt="the", max_new_tokens=5, top_k=100000, rng=rng)
        self.assertIsInstance(out, str)

    def test_generation_beyond_block_size_does_not_crash(self):
        rng = np.random.default_rng(0)
        out = sample(self.model, self.tok, prompt="the fox ran", max_new_tokens=40, rng=rng)
        self.assertIsInstance(out, str)

    def test_filter_logits_top_p_keeps_at_least_one(self):
        logits = np.array([5.0, 1.0, 0.5, -3.0])
        filtered = filter_logits(logits.copy(), top_p=1e-6)
        self.assertTrue(np.isfinite(filtered).sum() >= 1)

    def test_filter_logits_top_k_zero_is_noop(self):
        logits = np.array([1.0, 2.0, 3.0])
        filtered = filter_logits(logits.copy(), top_k=0)
        np.testing.assert_array_equal(filtered, logits)


class TestTrainLoop(unittest.TestCase):
    def test_get_batch_rejects_short_corpus(self):
        rng = np.random.default_rng(0)
        with self.assertRaises(ValueError):
            train_mod.get_batch(np.array([1, 2, 3]), block_size=10, batch_size=2, rng=rng)

    def test_short_training_run_reduces_loss(self):
        text = "the fox and the otter met by the river. " * 60
        tok = BPETokenizer()
        ids = tok.train(text, vocab_size=260)
        token_ids = np.array(ids)
        model = GPT(vocab_size=tok.vocab_size, block_size=16, n_layer=2, n_head=2, n_embd=16)
        opt = Adam(model, lr=3e-3)
        rng = np.random.default_rng(0)

        losses = []
        for _ in range(80):
            x, y = train_mod.get_batch(token_ids, block_size=16, batch_size=8, rng=rng)
            model.zero_grad()
            logits = model.forward(x)
            loss, dlogits = cross_entropy_loss(logits, y)
            model.backward(dlogits)
            opt.step()
            losses.append(loss)

        early_avg = np.mean(losses[:10])
        late_avg = np.mean(losses[-10:])
        self.assertLess(late_avg, early_avg)

    def test_checkpoint_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ckpt.pkl")
            tok = BPETokenizer()
            tok.train("hello world hello there world " * 10, vocab_size=270)
            config = dict(vocab_size=tok.vocab_size, block_size=8, n_layer=1, n_head=1, n_embd=8)
            model = GPT(**config)
            train_mod.save_checkpoint(path, model, tok, config, step=42, history={"step": [], "train_loss": [], "val_loss": []})

            loaded_model, loaded_tok, data = train_mod.load_checkpoint(path)
            self.assertEqual(data["step"], 42)
            idx = np.array([[1, 2, 3]])
            np.testing.assert_allclose(model.forward(idx), loaded_model.forward(idx))
            self.assertEqual(loaded_tok.encode("hello world"), tok.encode("hello world"))


if __name__ == "__main__":
    unittest.main()
