import unittest
import tempfile
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loom.nn import GPT
from loom.tokenizer import CharTokenizer
from loom.checkpoint import save_checkpoint, load_checkpoint


class TestCheckpoint(unittest.TestCase):
    def test_roundtrip_identical_outputs(self):
        np.random.seed(0)
        text = "the quick brown fox jumps over the lazy dog. " * 3
        tok = CharTokenizer(text)
        config = dict(vocab_size=tok.vocab_size, d_model=16, n_heads=2, n_layers=2, d_ff=32, max_seq_len=8)
        model = GPT(**config)

        idx = np.random.randint(0, tok.vocab_size, size=(1, 6))
        before = model(idx).data.copy()

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ckpt")
            save_checkpoint(path, model, tok, config)
            self.assertTrue(os.path.exists(path + ".npz"))
            self.assertTrue(os.path.exists(path + ".json"))

            model2, tok2, config2 = load_checkpoint(path)
            after = model2(idx).data.copy()

        np.testing.assert_allclose(before, after, atol=1e-10)
        self.assertEqual(tok2.vocab_size, tok.vocab_size)
        self.assertEqual(config2, config)

    def test_load_rejects_architecture_mismatch(self):
        np.random.seed(0)
        text = "abcdef" * 5
        tok = CharTokenizer(text)
        config = dict(vocab_size=tok.vocab_size, d_model=8, n_heads=2, n_layers=1, d_ff=16, max_seq_len=4)
        model = GPT(**config)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ckpt")
            save_checkpoint(path, model, tok, config)
            # Corrupt the saved config to claim a bigger architecture than the
            # weights actually stored -> must raise, not silently misload.
            import json
            with open(path + ".json") as f:
                meta = json.load(f)
            meta["config"]["n_layers"] = 5
            with open(path + ".json", "w") as f:
                json.dump(meta, f)
            with self.assertRaises(ValueError):
                load_checkpoint(path)


if __name__ == "__main__":
    unittest.main()
