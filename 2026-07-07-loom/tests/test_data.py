import numpy as np

from loom.data import Dataset


def test_get_batch_works_at_minimum_valid_corpus_length():
    """A corpus split of exactly block_size + 1 tokens is the shortest split
    that should ever be usable (it has exactly one valid (x, y) window). An
    off-by-one in the sampled-start upper bound used to make this crash with
    `ValueError: high <= 0` instead of working."""
    block_size = 16
    ids = np.arange(block_size + 1)
    ds = Dataset(ids, val_fraction=0.0)
    rng = np.random.default_rng(0)
    x, y = ds.get_batch("train", batch_size=4, block_size=block_size, rng=rng)
    assert x.shape == (4, block_size)
    assert y.shape == (4, block_size)
    # only one valid start (0) exists at this length - every row must be it
    assert np.array_equal(x, np.tile(np.arange(block_size), (4, 1)))


def test_get_batch_can_sample_the_last_valid_start():
    """The previous off-by-one excluded the final valid start index from
    ever being sampled, even once the corpus was comfortably longer than
    block_size + 1."""
    block_size = 4
    ids = np.arange(20)
    ds = Dataset(ids, val_fraction=0.0)
    rng = np.random.default_rng(0)
    last_start = len(ds.train_ids) - block_size - 1
    seen_last_start = False
    for _ in range(200):
        x, _ = ds.get_batch("train", batch_size=8, block_size=block_size, rng=rng)
        if any(row[0] == last_start for row in x):
            seen_last_start = True
            break
    assert seen_last_start, f"start index {last_start} was never sampled in 200 batches"


def test_get_batch_too_short_corpus_raises_clear_assertion():
    ids = np.arange(8)
    ds = Dataset(ids, val_fraction=0.0)
    rng = np.random.default_rng(0)
    try:
        ds.get_batch("train", batch_size=2, block_size=16, rng=rng)
        assert False, "expected an assertion error for a too-short corpus split"
    except AssertionError as e:
        assert "block_size" in str(e)
