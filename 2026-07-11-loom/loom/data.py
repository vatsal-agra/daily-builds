"""Corpus loading and minibatch sampling for causal language-model training."""
import numpy as np


class TextDataset:
    def __init__(self, token_ids, val_fraction=0.1):
        ids = np.asarray(token_ids, dtype=np.int64)
        if len(ids) < 2:
            raise ValueError("corpus must encode to at least 2 tokens")
        n_val = max(1, int(len(ids) * val_fraction)) if len(ids) > 10 else 0
        split = len(ids) - n_val
        self.train_ids = ids[:split] if split > 0 else ids
        self.val_ids = ids[split:] if n_val > 0 else ids[-2:]

    def get_batch(self, split, batch_size, block_size, rng):
        data = self.train_ids if split == "train" else self.val_ids
        if len(data) <= block_size:
            raise ValueError(
                f"{split} split has {len(data)} tokens, need > block_size={block_size}; "
                "use a larger corpus or a smaller block_size"
            )
        max_start = len(data) - block_size - 1
        starts = rng.integers(0, max_start + 1, size=batch_size)
        x = np.stack([data[s:s + block_size] for s in starts])
        y = np.stack([data[s + 1:s + block_size + 1] for s in starts])
        return x, y
