import json
import unittest

import numpy as np

from loom.nn import GPT
from loom.sample import _logits_to_probs, generate
from loom.tokenizer import ByteBPETokenizer


def _tiny_setup(seed=0):
    tok = ByteBPETokenizer()
    tok.train("the quick brown fox jumps over the lazy dog " * 10, num_merges=30)
    model = GPT(vocab_size=tok.vocab_size, block_size=16, n_embd=8, n_head=2, n_layer=1, seed=seed)
    return model, tok


class TestLogitsToProbs(unittest.TestCase):
    def test_sums_to_one(self):
        rng = np.random.default_rng(0)
        logits = rng.standard_normal(50)
        for top_k, top_p, temp in [(None, None, 1.0), (5, None, 0.7), (None, 0.9, 1.2), (5, 0.9, 0.5)]:
            probs = _logits_to_probs(logits, temp, top_k, top_p)
            self.assertAlmostEqual(probs.sum(), 1.0, places=8)
            self.assertTrue(np.all(probs >= 0))

    def test_top_k_zeroes_out_the_rest(self):
        logits = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        probs = _logits_to_probs(logits, temperature=1.0, top_k=2, top_p=None)
        self.assertEqual((probs > 0).sum(), 2)
        # the two largest logits (indices 0, 1) should be the surviving ones
        self.assertTrue(probs[0] > 0 and probs[1] > 0)

    def test_top_p_keeps_smallest_set_covering_mass(self):
        # a very peaked distribution: top_p=0.5 should keep only the single dominant token
        logits = np.array([100.0, 0.0, 0.0, 0.0])
        probs = _logits_to_probs(logits, temperature=1.0, top_k=None, top_p=0.5)
        self.assertEqual((probs > 0).sum(), 1)
        self.assertAlmostEqual(probs[0], 1.0, places=8)

    def test_temperature_zero_does_not_crash(self):
        logits = np.array([1.0, 2.0, 3.0])
        probs = _logits_to_probs(logits, temperature=0.0, top_k=None, top_p=None)
        self.assertAlmostEqual(probs.sum(), 1.0, places=8)


class TestGenerate(unittest.TestCase):
    def test_generate_respects_max_new_tokens(self):
        model, tok = _tiny_setup()
        text, trace = generate(model, tok, prompt="the", max_new_tokens=15, seed=0)
        self.assertEqual(len(trace), 15)

    def test_empty_prompt_zero_tokens_returns_empty_string(self):
        """Regression: generate(prompt='', max_new_tokens=0) used to emit one
        unrequested random seed character instead of ''."""
        model, tok = _tiny_setup()
        text, trace = generate(model, tok, prompt="", max_new_tokens=0, seed=0)
        self.assertEqual(text, "")
        self.assertEqual(trace, [])

    def test_empty_prompt_nonzero_tokens_still_generates(self):
        model, tok = _tiny_setup()
        text, trace = generate(model, tok, prompt="", max_new_tokens=10, seed=0)
        self.assertEqual(len(trace), 10)

    def test_long_prompt_is_truncated_to_block_size_context(self):
        model, tok = _tiny_setup()
        long_prompt = "the quick brown fox jumps over the lazy dog " * 5
        # should not raise even though encoded prompt exceeds block_size
        text, trace = generate(model, tok, prompt=long_prompt, max_new_tokens=5, seed=0)
        self.assertEqual(len(trace), 5)

    def test_capture_attn_produces_valid_trace_data(self):
        model, tok = _tiny_setup()
        text, trace = generate(model, tok, prompt="the", max_new_tokens=5, seed=0, capture_attn=True)
        for step in trace:
            self.assertIn("attn", step)
            self.assertIn("context_ids", step)
            self.assertEqual(len(step["attn"]), model.n_layer)
            # json-serializability (regression: numpy int64 seed tokens used
            # to sneak into context_ids and broke json.dumps downstream)
            json.dumps(step["context_ids"])

    def test_deterministic_with_fixed_seed(self):
        model, tok = _tiny_setup()
        text1, _ = generate(model, tok, prompt="the", max_new_tokens=10, seed=42)
        text2, _ = generate(model, tok, prompt="the", max_new_tokens=10, seed=42)
        self.assertEqual(text1, text2)


if __name__ == "__main__":
    unittest.main()
