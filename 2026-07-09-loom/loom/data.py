"""Batching over an encoded token-id array: random contiguous chunks of
length block_size+1, split into (x, y) where y is x shifted by one --
next-character prediction at every position, the standard LM training
target."""
import numpy as np


class Dataset:
    def __init__(self, ids, block_size, val_fraction=0.1, seed=0):
        self.ids = np.asarray(ids, dtype=np.int64)
        self.block_size = block_size
        if len(self.ids) < block_size + 1:
            raise ValueError(
                f"corpus has only {len(self.ids)} tokens, need at least block_size+1={block_size + 1}"
            )
        split = int(len(self.ids) * (1 - val_fraction))
        split = max(block_size + 1, min(split, len(self.ids) - (block_size + 1)))
        self.train_ids = self.ids[:split]
        self.val_ids = self.ids[split:]
        self.rng = np.random.RandomState(seed)

    def get_batch(self, batch_size, split="train"):
        ids = self.train_ids if split == "train" else self.val_ids
        max_start = len(ids) - self.block_size - 1
        starts = self.rng.randint(0, max_start + 1, size=batch_size)
        x = np.stack([ids[s:s + self.block_size] for s in starts])
        y = np.stack([ids[s + 1:s + 1 + self.block_size] for s in starts])
        return x, y
