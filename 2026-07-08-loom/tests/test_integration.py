import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from loom.checkpoint import load_checkpoint, save_checkpoint  # noqa: E402
from loom.nn import GPT  # noqa: E402
from loom.optim import Adam, clip_grad_norm, lr_schedule  # noqa: E402
from loom.tensor import no_grad  # noqa: E402
from loom.tokenizer import BPETokenizer  # noqa: E402
from loom.train import build_argparser, estimate_loss, get_batch, train  # noqa: E402

TOY_CORPUS = (
    "the quick brown fox jumps over the lazy dog. "
    "the dog barks at the fox. the fox runs away quickly. " * 40
)


class TestTrainingReducesLoss(unittest.TestCase):
    def test_loss_decreases_over_training(self):
        rng = np.random.default_rng(0)
        tok = BPETokenizer()
        tok.train(TOY_CORPUS, vocab_size=280)
        ids = np.array(tok.encode(TOY_CORPUS), dtype=np.int64)

        model = GPT(vocab_size=tok.vocab_size, n_embd=32, n_head=4, n_layer=2, block_size=32)
        opt = Adam(model.parameters(), lr=5e-3)

        losses = []
        for step in range(60):
            x, y = get_batch(ids, block_size=32, batch_size=8, rng=rng)
            _, loss = model(x, targets=y)
            opt.zero_grad()
            loss.backward()
            clip_grad_norm(model.parameters(), 1.0)
            opt.step()
            losses.append(loss.item())

        early = np.mean(losses[:5])
        late = np.mean(losses[-5:])
        self.assertLess(late, early * 0.7, f"loss did not drop enough: {early:.3f} -> {late:.3f}")

    def test_lr_schedule_warmup_then_decay(self):
        warmup, total, base = 10, 100, 1e-3
        lrs = [lr_schedule(s, warmup, total, base) for s in range(total + 20)]
        # warmup is monotonically increasing
        for i in range(1, warmup):
            self.assertGreater(lrs[i], lrs[i - 1])
        # after warmup, generally decreasing (cosine decay), and past `total`
        # steps it holds at the floor
        self.assertAlmostEqual(lrs[-1], lrs[-2], places=8)
        self.assertLess(lrs[total], lrs[warmup])


class TestCheckpointRoundtrip(unittest.TestCase):
    def test_save_load_gives_identical_outputs(self):
        model = GPT(vocab_size=50, n_embd=16, n_head=2, n_layer=2, block_size=16)
        idx = np.random.randint(0, 50, size=(2, 8))
        with no_grad():
            logits_before, _ = model(idx)

        config = {"vocab_size": 50, "n_embd": 16, "n_head": 2, "n_layer": 2, "block_size": 16}
        with tempfile.TemporaryDirectory() as d:
            weights_path = os.path.join(d, "model.npz")
            config_path = os.path.join(d, "config.json")
            save_checkpoint(model, config, weights_path, config_path)
            loaded_model, loaded_config = load_checkpoint(weights_path, config_path)

        self.assertEqual(loaded_config, config)
        with no_grad():
            logits_after, _ = loaded_model(idx)
        self.assertTrue(np.allclose(logits_before.data, logits_after.data))

    def test_load_checkpoint_rejects_shape_mismatch(self):
        model = GPT(vocab_size=50, n_embd=16, n_head=2, n_layer=1, block_size=16)
        config = {"vocab_size": 50, "n_embd": 16, "n_head": 2, "n_layer": 1, "block_size": 16}
        with tempfile.TemporaryDirectory() as d:
            weights_path = os.path.join(d, "model.npz")
            config_path = os.path.join(d, "config.json")
            save_checkpoint(model, config, weights_path, config_path)
            # now claim a DIFFERENT n_embd in the config than the saved weights match
            bad_config = dict(config, n_embd=32)
            import json

            with open(config_path, "w") as f:
                json.dump(bad_config, f)
            with self.assertRaises(ValueError):
                load_checkpoint(weights_path, config_path)


class TestEndToEndTrainPipeline(unittest.TestCase):
    def test_train_function_end_to_end_and_checkpoint_is_usable(self):
        with tempfile.TemporaryDirectory() as d:
            corpus_path = os.path.join(d, "corpus.txt")
            with open(corpus_path, "w") as f:
                f.write(TOY_CORPUS)
            out_dir = os.path.join(d, "ckpt")
            args = build_argparser().parse_args([
                "--corpus", corpus_path,
                "--out-dir", out_dir,
                "--vocab-size", "260",
                "--n-embd", "16",
                "--n-head", "2",
                "--n-layer", "1",
                "--block-size", "16",
                "--batch-size", "4",
                "--steps", "10",
                "--warmup-steps", "2",
                "--eval-every", "5",
                "--eval-iters", "2",
                "--log-every", "5",
                "--val-frac", "0.2",
            ])
            train(args)

            self.assertTrue(os.path.exists(os.path.join(out_dir, "model.npz")))
            self.assertTrue(os.path.exists(os.path.join(out_dir, "config.json")))
            self.assertTrue(os.path.exists(os.path.join(out_dir, "tokenizer.json")))

            from loom.generate import generate_text, load_generator

            model, tok, config = load_generator(out_dir)
            text = generate_text(model, tok, "the quick", max_new_tokens=20, seed=0)
            self.assertIsInstance(text, str)
            self.assertGreater(len(text), len("the quick"))

    def test_get_batch_rejects_corpus_shorter_than_block_size(self):
        ids = np.arange(5)
        with self.assertRaises(ValueError):
            get_batch(ids, block_size=32, batch_size=4, rng=np.random.default_rng(0))


if __name__ == "__main__":
    unittest.main()
