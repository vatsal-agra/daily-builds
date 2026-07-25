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
from loom.optimizer import AdamW, clip_grad_global_norm, warmup_cosine_lr


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


def test_nan_grad_raises_instead_of_corrupting():
    # NaN/Inf compare False to everything in Python, so `norm > max_norm`
    # would silently skip clipping and let a diverged run's NaN gradients
    # flow straight into AdamW. clip_grad_global_norm must catch this itself.
    grads = {"a": np.array([np.nan, 1.0]), "b": np.array([2.0])}
    try:
        clip_grad_global_norm(grads, 1.0)
        raised = False
    except FloatingPointError:
        raised = True
    assert raised, "non-finite gradients must raise, not silently pass through unclipped"
    print("  NaN-gradient guard: raises FloatingPointError instead of corrupting training")


def test_lr_schedule_edges():
    # warmup_steps=0 must not divide by zero, and step beyond total_steps
    # must clamp at the configured floor rather than extrapolating the cosine.
    lr0 = warmup_cosine_lr(0, 0, 100, 1e-3)
    assert np.isfinite(lr0) and lr0 > 0
    lr_far = warmup_cosine_lr(1000, 10, 100, 1e-3, min_lr_ratio=0.1)
    assert abs(lr_far - 1e-4) < 1e-12, f"expected floor lr 1e-4, got {lr_far}"
    print("  LR schedule edge cases (warmup=0, step past total_steps): OK")


if __name__ == "__main__":
    test_shapes()
    test_causal_mask_no_leakage()
    test_overfit_tiny_batch()
    test_nan_grad_raises_instead_of_corrupting()
    test_lr_schedule_edges()
    print("ALL MODEL TESTS PASSED")
