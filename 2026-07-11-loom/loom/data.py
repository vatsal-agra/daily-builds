"""Corpus loading and minibatch sampling for causal language-model training."""
import numpy as np


class TextDataset:
    """Splits `token_ids` into train/val. The val split is always sized to
    hold at least one full `block_size` training example -- a naive
    `val_fraction`-only split can produce a val set smaller than
    `block_size` for modest corpora, which used to crash `get_batch`
    partway through a training run (see REVIEW.md finding #1). For corpora
    too small to hold out a genuine val split at all, both splits fall back
    to the full corpus (`has_held_out_val` records which case happened)."""

    def __init__(self, token_ids, block_size, val_fraction=0.1):
        ids = np.asarray(token_ids, dtype=np.int64)
        min_len = block_size + 2
        if len(ids) < min_len:
            raise ValueError(f"corpus encodes to only {len(ids)} tokens, need > block_size+1={min_len - 1}")

        if len(ids) < 2 * min_len:
            self.train_ids = ids
            self.val_ids = ids
            self.has_held_out_val = False
            return

        n_val = max(min_len, int(len(ids) * val_fraction))
        split = len(ids) - n_val
        self.train_ids = ids[:split]
        self.val_ids = ids[split:]
        self.has_held_out_val = True

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
