"""
Model-level sanity checks that gradcheck alone can't catch:
- shapes are right
- the causal mask actually prevents future tokens from leaking into past logits
- the full train step (forward + backward + AdamW) can memorize a tiny batch
  to near-zero loss, proving the wiring between all the pieces is correct.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom.model import GPT, GPTConfig
from loom.optimizer import AdamW, clip_grad_global_norm


def test_shapes():
    cfg = GPTConfig(vocab_size=50, n_ctx=16, n_embd=32, n_head=4, n_layer=2)
    model = GPT(cfg, seed=0)
    idx = np.random.default_rng(0).integers(0, 50, size=(3, 10))
    logits = model.forward(idx)
    assert logits.shape == (3, 10, 50), logits.shape
    print("  shapes: OK")


def test_causal_mask_no_leakage():
    cfg = GPTConfig(vocab_size=30, n_ctx=8, n_embd=16, n_head=2, n_layer=2)
    model = GPT(cfg, seed=0)
    rng = np.random.default_rng(1)
    idx = rng.integers(0, 30, size=(1, 8))

    logits_a = model.forward(idx.copy())

    idx_b = idx.copy()
    idx_b[0, -1] = (idx_b[0, -1] + 1) % 30  # change only the LAST token
    logits_b = model.forward(idx_b)

    # every position except the last must be byte-for-byte identical:
    # a causal model's logits at position t can only depend on tokens <= t.
    assert np.allclose(logits_a[:, :-1, :], logits_b[:, :-1, :]), (
        "changing the last input token altered earlier positions' logits — "
        "causal mask is leaking future information into the past"
    )
    assert not np.allclose(logits_a[:, -1, :], logits_b[:, -1, :]), (
        "changing the last token should change its own next-token prediction"
    )
    print("  causal mask: no leakage from future to past, last position IS affected")


def test_overfit_tiny_batch():
    cfg = GPTConfig(vocab_size=12, n_ctx=8, n_embd=32, n_head=4, n_layer=2)
    model = GPT(cfg, seed=0)
    rng = np.random.default_rng(2)
    x = rng.integers(0, 12, size=(4, 8))
    y = rng.integers(0, 12, size=(4, 8))

    opt = AdamW(model.params(), lr=5e-3, weight_decay=0.0)
    losses = []
    for step in range(400):
        loss, _ = model.loss(x, y)
        clip_grad_global_norm(model.grads, 1.0)
        opt.step(model.grads)
        losses.append(loss)

    assert losses[0] > 2.0, f"initial loss suspiciously low: {losses[0]}"
    assert losses[-1] < 0.05, f"failed to memorize tiny batch: final loss {losses[-1]:.4f}"
    print(f"  overfit sanity check: loss {losses[0]:.3f} -> {losses[-1]:.4f} over 400 steps")


if __name__ == "__main__":
    test_shapes()
    test_causal_mask_no_leakage()
    test_overfit_tiny_batch()
    print("ALL MODEL TESTS PASSED")
