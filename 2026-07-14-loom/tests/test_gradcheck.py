import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom.gradcheck import gradcheck_model
from loom.model import TransformerLM


class TestGradCheck(unittest.TestCase):
    def _run(self, **kwargs):
        cfg = dict(vocab_size=13, d_model=8, n_heads=2, n_layers=2, max_seq_len=6)
        cfg.update(kwargs)
        rng = np.random.RandomState(0)
        model = TransformerLM(seed=1, **cfg)
        ids = rng.randint(0, cfg["vocab_size"], size=(3, 5))
        targets = rng.randint(0, cfg["vocab_size"], size=(3, 5))
        return gradcheck_model(model, ids, targets, num_samples=4, seed=7)

    def test_two_layer_two_head(self):
        results = self._run()
        self.assertTrue(all(r["ok"] for r in results))
        self.assertGreater(len(results), 10)

    def test_single_layer_single_head(self):
        results = self._run(n_layers=1, n_heads=1, d_model=6)
        self.assertTrue(all(r["ok"] for r in results))

    def test_four_layers(self):
        results = self._run(n_layers=4, d_model=8, n_heads=4)
        self.assertTrue(all(r["ok"] for r in results))

    def test_batch_size_one(self):
        rng = np.random.RandomState(0)
        model = TransformerLM(vocab_size=10, d_model=8, n_heads=2, n_layers=2, max_seq_len=4, seed=2)
        ids = rng.randint(0, 10, size=(1, 4))
        targets = rng.randint(0, 10, size=(1, 4))
        results = gradcheck_model(model, ids, targets, num_samples=4, seed=3)
        self.assertTrue(all(r["ok"] for r in results))

    def test_sequence_length_one(self):
        rng = np.random.RandomState(0)
        model = TransformerLM(vocab_size=10, d_model=8, n_heads=2, n_layers=1, max_seq_len=4, seed=2)
        ids = rng.randint(0, 10, size=(2, 1))
        targets = rng.randint(0, 10, size=(2, 1))
        results = gradcheck_model(model, ids, targets, num_samples=4, seed=3)
        self.assertTrue(all(r["ok"] for r in results))


if __name__ == "__main__":
    unittest.main()
