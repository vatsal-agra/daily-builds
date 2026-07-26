import json
import os
import tempfile
import unittest

from loom import checkpoint
from loom.sample import generate
from loom.train import train

CORPUS = (
    "the quick brown fox jumps over the lazy dog. " * 20 +
    "to be or not to be, that is the question, whether tis nobler in the mind. "
)


class TestTrain(unittest.TestCase):
    def test_loss_strictly_decreases_over_training(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, history = train(
                CORPUS, out_dir=d, num_merges=80, block_size=32, n_embd=16, n_head=2, n_layer=1,
                batch_size=8, steps=120, eval_every=20, seed=0,
                log_fn=lambda *a, **k: None,
            )
        self.assertGreaterEqual(len(history), 2)
        self.assertLess(history[-1]["train_loss"], history[0]["train_loss"])
        # should get well below the "no learning" floor (uniform log(vocab_size))
        self.assertLess(history[-1]["train_loss"], history[0]["train_loss"] * 0.8)

    def test_checkpoint_round_trip_preserves_generation(self):
        with tempfile.TemporaryDirectory() as d:
            model, tokenizer, _ = train(
                CORPUS, out_dir=d, num_merges=60, block_size=24, n_embd=16, n_head=2, n_layer=1,
                batch_size=8, steps=20, eval_every=10, seed=0,
                log_fn=lambda *a, **k: None,
            )
            text_before, _ = generate(model, tokenizer, prompt="the", max_new_tokens=20, seed=0)

            model2, tokenizer2, meta = checkpoint.load(d)
            text_after, _ = generate(model2, tokenizer2, prompt="the", max_new_tokens=20, seed=0)

        self.assertEqual(text_before, text_after)
        self.assertEqual(tokenizer.merges, tokenizer2.merges)
        self.assertIn("history", meta)

    def test_checkpoint_shape_mismatch_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            train(
                CORPUS, out_dir=d, num_merges=30, block_size=16, n_embd=8, n_head=2, n_layer=1,
                batch_size=4, steps=5, eval_every=5, seed=0, log_fn=lambda *a, **k: None,
            )
            # corrupt the meta to claim a different architecture than the saved params
            meta_path = os.path.join(d, "meta.json")
            with open(meta_path) as f:
                meta = json.load(f)
            meta["n_layer"] = 3
            with open(meta_path, "w") as f:
                json.dump(meta, f)
            with self.assertRaises(ValueError):
                checkpoint.load(d)

    def test_rejects_too_small_corpus(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                train("hi", out_dir=d, steps=5, log_fn=lambda *a, **k: None)


if __name__ == "__main__":
    unittest.main()
