import unittest
import sys
import os

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loom.generate import sample_next, _filter_logits, generate
from loom.nn import GPT
from loom.tokenizer import CharTokenizer


class TestFilterLogits(unittest.TestCase):
    def test_top_k_keeps_only_k(self):
        logits = np.array([1.0, 5.0, 2.0, 4.0, 0.0])
        out = _filter_logits(logits.copy(), top_k=2)
        finite = np.isfinite(out)
        self.assertEqual(finite.sum(), 2)
        self.assertTrue(out[1] == 5.0 and out[3] == 4.0)

    def test_top_p_keeps_smallest_covering_set(self):
        # heavily peaked distribution: first logit should dominate top_p=0.5
        logits = np.log(np.array([0.9, 0.05, 0.03, 0.02]))
        out = _filter_logits(logits.copy(), top_p=0.5)
        finite_idx = np.where(np.isfinite(out))[0]
        self.assertIn(0, finite_idx)
        self.assertNotIn(3, finite_idx)


class TestSampleNext(unittest.TestCase):
    def test_temperature_zero_is_argmax(self):
        logits = np.array([0.1, 5.0, -3.0, 2.0])
        self.assertEqual(sample_next(logits, temperature=0.0), 1)

    def test_seeded_rng_is_deterministic(self):
        logits = np.random.RandomState(1).randn(20)
        rng1 = np.random.default_rng(42)
        rng2 = np.random.default_rng(42)
        a = sample_next(logits, temperature=1.0, rng=rng1)
        b = sample_next(logits, temperature=1.0, rng=rng2)
        self.assertEqual(a, b)


class TestGenerateIntegration(unittest.TestCase):
    def test_generate_produces_correct_length_and_valid_chars(self):
        np.random.seed(0)
        text = "abcabcabcabcabcabc"
        tok = CharTokenizer(text)
        model = GPT(vocab_size=tok.vocab_size, d_model=8, n_heads=2, n_layers=1, d_ff=16, max_seq_len=6)
        out = generate(model, tok, prompt="ab", max_new_tokens=10, temperature=1.0, seed=0)
        self.assertEqual(len(out), 12)
        self.assertTrue(all(c in tok.stoi for c in out))

    def test_generate_with_no_prompt_falls_back_to_id_zero_if_no_space_in_vocab(self):
        # This corpus never contains a space, so the " " seed fallback must
        # itself fall back to raw token id 0 instead of crashing.
        np.random.seed(0)
        text = "xyz" * 5
        tok = CharTokenizer(text)
        model = GPT(vocab_size=tok.vocab_size, d_model=8, n_heads=2, n_layers=1, d_ff=16, max_seq_len=6)
        out = generate(model, tok, prompt="", max_new_tokens=5, seed=0)
        self.assertEqual(len(out), 6)

    def test_generate_with_no_prompt_seeds_with_space_when_available(self):
        np.random.seed(0)
        text = "the fox and the hound " * 5
        tok = CharTokenizer(text)
        model = GPT(vocab_size=tok.vocab_size, d_model=8, n_heads=2, n_layers=1, d_ff=16, max_seq_len=6)
        out = generate(model, tok, prompt="", max_new_tokens=5, seed=0)
        self.assertEqual(out[0], " ")
        self.assertEqual(len(out), 6)

    def test_generate_never_exceeds_block_size_context(self):
        """Long prompts must be truncated to the last block_size tokens,
        never silently overflow the positional embedding table."""
        np.random.seed(0)
        text = "abcdefgh" * 3
        tok = CharTokenizer(text)
        model = GPT(vocab_size=tok.vocab_size, d_model=8, n_heads=2, n_layers=1, d_ff=16, max_seq_len=4)
        long_prompt = "abcdefgh" * 2  # 16 chars, way more than max_seq_len=4
        out = generate(model, tok, prompt=long_prompt, max_new_tokens=3, seed=0)
        self.assertEqual(len(out), len(long_prompt) + 3)


if __name__ == "__main__":
    unittest.main()
