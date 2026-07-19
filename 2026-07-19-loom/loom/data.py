"""Corpus loading and sliding-window minibatch sampling."""
import numpy as np


def load_corpus(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def train_val_split(ids, val_fraction=0.1):
    n = len(ids)
    split = int(n * (1 - val_fraction))
    return ids[:split], ids[split:]


def get_batch(ids, batch_size, block_size, rng):
    """Random contiguous windows of length block_size; targets are the
    same window shifted by one (next-token prediction)."""
    n = len(ids)
    max_start = n - block_size - 1
    if max_start < 1:
        raise ValueError(
            f"corpus of {n} tokens is too short for block_size={block_size}"
        )
    starts = rng.integers(0, max_start, size=batch_size)
    x = np.stack([ids[s:s + block_size] for s in starts])
    y = np.stack([ids[s + 1:s + block_size + 1] for s in starts])
    return x, y
