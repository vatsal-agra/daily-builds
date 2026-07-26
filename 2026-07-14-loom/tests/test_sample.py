import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom.model import TransformerLM
from loom.sample import filter_logits, generate
from loom.tokenizer import BPETokenizer

TOY_CORPUS = "the quick brown fox jumps over the lazy dog " * 50


def _tiny_setup():
    tok = BPETokenizer()
    tok.train(TOY_CORPUS, vocab_size=270)
    model = TransformerLM(vocab_size=tok.vocab_size, d_model=16, n_heads=2,
                           n_layers=2, max_seq_len=32, seed=0)
    return model, tok


class TestFilterLogits(unittest.TestCase):
    def test_top_k_keeps_exactly_k(self):
        logits = np.array([1.0, 5.0, 2.0, 9.0, 0.0])
        out = filter_logits(logits, top_k=2)
        self.assertEqual(np.sum(np.isfinite(out)), 2)
        self.assertTrue(np.isfinite(out[3]) and np.isfinite(out[1]))

    def test_top_k_larger_than_vocab_is_noop(self):
        logits = np.array([1.0, 5.0, 2.0])
        out = filter_logits(logits, top_k=100)
        np.testing.assert_array_equal(out, logits)

    def test_top_p_keeps_smallest_sufficient_set(self):
        # heavily peaked distribution: one dominant logit
        logits = np.array([10.0, 0.0, 0.0, 0.0])
        out = filter_logits(logits, top_p=0.9)
        self.assertEqual(np.sum(np.isfinite(out)), 1)

    def test_no_filter_is_noop(self):
        logits = np.array([1.0, 2.0, 3.0])
        out = filter_logits(logits)
        np.testing.assert_array_equal(out, logits)


class TestGenerate(unittest.TestCase):
    def test_greedy_is_deterministic_and_valid_ids(self):
        model, tok = _tiny_setup()
        text1, ids1 = generate(model, tok, "the", max_new_tokens=15, temperature=0.0)
        text2, ids2 = generate(model, tok, "the", max_new_tokens=15, temperature=0.0)
        self.assertEqual(ids1, ids2)
        self.assertTrue(all(0 <= i < tok.vocab_size for i in ids1))

    def test_temperature_zero_matches_top_k_one(self):
        model, tok = _tiny_setup()
        _, ids_greedy = generate(model, tok, "the quick", max_new_tokens=10, temperature=0.0)
        _, ids_topk1 = generate(model, tok, "the quick", max_new_tokens=10, temperature=1.0,
                                 top_k=1, seed=0)
        self.assertEqual(ids_greedy, ids_topk1)

    def test_sampling_is_seed_reproducible(self):
        model, tok = _tiny_setup()
        _, ids_a = generate(model, tok, "fox", max_new_tokens=20, temperature=1.0, seed=123)
        _, ids_b = generate(model, tok, "fox", max_new_tokens=20, temperature=1.0, seed=123)
        self.assertEqual(ids_a, ids_b)

    def test_different_seeds_can_diverge(self):
        model, tok = _tiny_setup()
        _, ids_a = generate(model, tok, "fox", max_new_tokens=30, temperature=1.2, seed=1)
        _, ids_b = generate(model, tok, "fox", max_new_tokens=30, temperature=1.2, seed=2)
        self.assertNotEqual(ids_a, ids_b)

    def test_empty_prompt_does_not_crash(self):
        model, tok = _tiny_setup()
        text, ids = generate(model, tok, "", max_new_tokens=10, temperature=0.7, seed=0)
        self.assertIsInstance(text, str)
        self.assertGreater(len(ids), 0)

    def test_negative_temperature_raises(self):
        model, tok = _tiny_setup()
        with self.assertRaises(ValueError):
            generate(model, tok, "the", max_new_tokens=5, temperature=-1.0)

    def test_context_longer_than_max_seq_len_is_truncated_not_error(self):
        model, tok = _tiny_setup()
        long_prompt = "the quick brown fox " * 20  # well beyond max_seq_len=32 tokens
        text, ids = generate(model, tok, long_prompt, max_new_tokens=5, temperature=0.5, seed=0)
        self.assertIsInstance(text, str)


if __name__ == "__main__":
    unittest.main()
