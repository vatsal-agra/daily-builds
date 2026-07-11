import unittest

import numpy as np

from loom.data import TextDataset


class TestTextDataset(unittest.TestCase):
    def test_large_corpus_gets_a_real_held_out_val_split(self):
        ids = list(range(2000))
        ds = TextDataset(ids, block_size=32)
        self.assertTrue(ds.has_held_out_val)
        self.assertGreater(len(ds.val_ids), 32)
        self.assertGreater(len(ds.train_ids), 32)
        # splits shouldn't overlap
        self.assertEqual(len(ds.train_ids) + len(ds.val_ids), 2000)

    def test_modest_corpus_no_longer_crashes_get_batch_on_val_split(self):
        """Regression for REVIEW.md finding #1: a corpus just barely over
        block_size used to carve out a val split smaller than block_size,
        crashing get_batch('val', ...) partway through training."""
        ids = list(range(150))
        ds = TextDataset(ids, block_size=64)
        rng = np.random.default_rng(0)
        x, y = ds.get_batch("val", batch_size=8, block_size=64, rng=rng)
        self.assertEqual(x.shape, (8, 64))
        self.assertEqual(y.shape, (8, 64))

    def test_tiny_corpus_falls_back_to_shared_split_instead_of_crashing(self):
        ids = list(range(70))  # just over block_size+2, too small for two real splits
        ds = TextDataset(ids, block_size=64)
        self.assertFalse(ds.has_held_out_val)
        np.testing.assert_array_equal(ds.train_ids, ds.val_ids)
        rng = np.random.default_rng(0)
        x, y = ds.get_batch("val", batch_size=4, block_size=64, rng=rng)
        self.assertEqual(x.shape, (4, 64))

    def test_corpus_too_small_for_block_size_raises_clear_error(self):
        with self.assertRaises(ValueError):
            TextDataset(list(range(10)), block_size=64)

    def test_get_batch_targets_are_shifted_by_one(self):
        ids = list(range(500))
        ds = TextDataset(ids, block_size=16)
        rng = np.random.default_rng(0)
        x, y = ds.get_batch("train", batch_size=4, block_size=16, rng=rng)
        np.testing.assert_array_equal(x[:, 1:], y[:, :-1])


if __name__ == "__main__":
    unittest.main()
