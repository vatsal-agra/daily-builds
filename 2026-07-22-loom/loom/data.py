"""Corpus loading and minibatch sampling."""

import numpy as np


def load_and_split(corpus_path, tokenizer, val_fraction=0.1):
    text = open(corpus_path, encoding="utf-8").read()
    ids = np.array(tokenizer.encode(text), dtype=np.int64)
    n_val = max(1, int(len(ids) * val_fraction))
    train_ids = ids[:-n_val]
    val_ids = ids[-n_val:]
    return train_ids, val_ids


def get_batch(data_ids, batch_size, block_size, rng):
    """Sample ``batch_size`` random contiguous windows of length ``block_size``.

    Returns (x, y) int arrays of shape (batch_size, block_size), where
    y[i] is x[i] shifted one token to the right (the next-token targets).
    """
    max_start = len(data_ids) - block_size - 1
    assert max_start > 0, "corpus too short for this block_size"
    starts = rng.integers(0, max_start, size=batch_size)
    x = np.stack([data_ids[s:s + block_size] for s in starts])
    y = np.stack([data_ids[s + 1:s + 1 + block_size] for s in starts])
    return x, y
