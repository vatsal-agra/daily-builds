import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom.optim import Adam, clip_grad_norm, lr_schedule
from loom.nn import Parameter
from loom.train import load_checkpoint, make_batch, train

TOY_CORPUS = (
    "the quick brown fox jumps over the lazy dog. " * 300
    + "pack my box with five dozen liquor jugs. " * 300
)


class TestOptim(unittest.TestCase):
    def test_adam_reduces_simple_quadratic_loss(self):
        p = Parameter(np.array([5.0, -3.0]))
        opt = Adam([p], lr=0.1)
        for _ in range(200):
            p.grad[...] = 2 * p.value  # d/dx x^2
            opt.step()
            opt.zero_grad()
        self.assertLess(np.abs(p.value).max(), 1e-2)

    def test_clip_grad_norm_caps_norm(self):
        p = Parameter(np.zeros(4))
        p.grad[...] = np.array([10.0, 0, 0, 0])
        total = clip_grad_norm([p], max_norm=1.0)
        self.assertAlmostEqual(total, 10.0)
        self.assertAlmostEqual(float(np.linalg.norm(p.grad)), 1.0, places=5)

    def test_clip_grad_norm_noop_when_under_limit(self):
        p = Parameter(np.zeros(4))
        p.grad[...] = np.array([0.1, 0, 0, 0])
        clip_grad_norm([p], max_norm=1.0)
        self.assertAlmostEqual(float(p.grad[0]), 0.1)

    def test_lr_schedule_warmup_then_decay(self):
        self.assertAlmostEqual(lr_schedule(0, 10, 100, 1.0), 0.1)
        self.assertAlmostEqual(lr_schedule(9, 10, 100, 1.0), 1.0)
        self.assertLess(lr_schedule(99, 10, 100, 1.0), 1.0)
        self.assertGreaterEqual(lr_schedule(99, 10, 100, 1.0), 0.1 * 1.0 - 1e-9)


class TestMakeBatch(unittest.TestCase):
    def test_shapes_and_shift(self):
        ids = np.arange(100)
        rng = np.random.RandomState(0)
        x, y = make_batch(ids, batch_size=4, seq_len=10, rng=rng)
        self.assertEqual(x.shape, (4, 10))
        self.assertEqual(y.shape, (4, 10))
        np.testing.assert_array_equal(x[:, 1:], y[:, :-1])

    def test_too_short_corpus_raises(self):
        ids = np.arange(5)
        rng = np.random.RandomState(0)
        with self.assertRaises(ValueError):
            make_batch(ids, batch_size=2, seq_len=10, rng=rng)


class TestTrain(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.corpus_path = os.path.join(self.tmpdir, "corpus.txt")
        with open(self.corpus_path, "w") as f:
            f.write(TOY_CORPUS)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_loss_decreases_over_training(self):
        out_dir = os.path.join(self.tmpdir, "run")
        model, tok, losses = train(
            corpus_path=self.corpus_path, out_dir=out_dir, vocab_size=280,
            d_model=32, n_heads=2, n_layers=2, seq_len=32, batch_size=16,
            steps=150, lr=5e-3, warmup_steps=15, seed=0, log_every=50,
            ckpt_every=150, verbose=False,
        )
        early_avg = np.mean(losses[:10])
        late_avg = np.mean(losses[-10:])
        self.assertLess(late_avg, early_avg * 0.85)

    def test_checkpoint_files_written_and_loadable(self):
        out_dir = os.path.join(self.tmpdir, "run2")
        train(
            corpus_path=self.corpus_path, out_dir=out_dir, vocab_size=270,
            d_model=16, n_heads=2, n_layers=1, seq_len=16, batch_size=8,
            steps=10, lr=1e-3, warmup_steps=2, seed=0, log_every=5,
            ckpt_every=10, verbose=False,
        )
        self.assertTrue(os.path.exists(os.path.join(out_dir, "model.npz")))
        self.assertTrue(os.path.exists(os.path.join(out_dir, "config.json")))
        self.assertTrue(os.path.exists(os.path.join(out_dir, "tokenizer.json")))
        self.assertTrue(os.path.exists(os.path.join(out_dir, "train_log.jsonl")))

        model = load_checkpoint(
            os.path.join(out_dir, "model.npz"), os.path.join(out_dir, "config.json")
        )
        ids = np.zeros((1, 4), dtype=np.int64)
        logits, _ = model.forward(ids)
        self.assertTrue(np.all(np.isfinite(logits)))

        with open(os.path.join(out_dir, "train_log.jsonl")) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        self.assertGreater(len(lines), 0)
        for rec in lines:
            self.assertIn("step", rec)
            self.assertIn("loss", rec)

    def test_empty_corpus_raises(self):
        empty_path = os.path.join(self.tmpdir, "empty.txt")
        open(empty_path, "w").close()
        with self.assertRaises(ValueError):
            train(corpus_path=empty_path, out_dir=os.path.join(self.tmpdir, "run3"),
                  vocab_size=256, steps=1, verbose=False)


if __name__ == "__main__":
    unittest.main()
