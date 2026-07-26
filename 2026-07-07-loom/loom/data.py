"""Corpus loading, tokenization, and random minibatch sampling."""
import numpy as np


class Dataset:
    def __init__(self, token_ids, val_fraction=0.1):
        ids = np.asarray(token_ids, dtype=np.int64)
        split = int(len(ids) * (1 - val_fraction))
        self.train_ids = ids[:split]
        self.val_ids = ids[split:]

    def get_batch(self, split, batch_size, block_size, rng):
        ids = self.train_ids if split == "train" else self.val_ids
        assert len(ids) > block_size, "corpus split shorter than block_size"
        # y needs ids[s + block_size], so the last valid start is
        # len(ids) - block_size - 1; integers()'s upper bound is exclusive,
        # so it must be len(ids) - block_size, not - 1 further (that extra
        # -1 silently excluded the last valid start, and made every corpus
        # split of length exactly block_size + 1 raise `high <= 0`).
        starts = rng.integers(0, len(ids) - block_size, size=batch_size)
        x = np.stack([ids[s:s + block_size] for s in starts])
        y = np.stack([ids[s + 1:s + block_size + 1] for s in starts])
        return x, y
