import numpy as np

from loom.optim import Adam, lr_schedule
from loom.tensor import Tensor


def test_adam_minimizes_quadratic_bowl():
    """Simple sanity check for the from-scratch Adam implementation: it
    should be able to drive a convex quadratic to its minimum."""
    rng = np.random.default_rng(0)
    x = Tensor(rng.normal(size=(5,)) * 5, requires_grad=True)
    target = Tensor(rng.normal(size=(5,)))
    opt = Adam([x], lr=0.1)

    for _ in range(500):
        diff = x - target
        loss = (diff * diff).sum()
        opt.zero_grad()
        loss.backward()
        opt.step()

    assert np.allclose(x.data, target.data, atol=1e-2)


def test_grad_clip_norm_shrinks_large_gradients():
    x = Tensor(np.zeros(3), requires_grad=True)
    x.grad = np.array([3.0, 4.0, 0.0])  # norm 5
    opt = Adam([x])
    total_before = opt.clip_grad_norm(max_norm=1.0)
    assert np.isclose(total_before, 5.0)
    assert np.isclose(np.linalg.norm(x.grad), 1.0, atol=1e-4)


def test_grad_clip_norm_leaves_small_gradients_untouched():
    x = Tensor(np.zeros(3), requires_grad=True)
    x.grad = np.array([0.1, 0.0, 0.0])
    opt = Adam([x])
    opt.clip_grad_norm(max_norm=1.0)
    assert np.allclose(x.grad, [0.1, 0.0, 0.0])


def test_lr_schedule_warmup_then_cosine_decay():
    warmup, total, base = 100, 1000, 1e-3
    # warmup ramps up
    lr0 = lr_schedule(0, warmup, total, base)
    lr_mid_warmup = lr_schedule(50, warmup, total, base)
    lr_end_warmup = lr_schedule(warmup, warmup, total, base)
    assert lr0 < lr_mid_warmup < lr_end_warmup

    # decays after warmup, ends near min_lr_ratio * base
    lr_far = lr_schedule(total - 1, warmup, total, base, min_lr_ratio=0.1)
    assert lr_far < lr_end_warmup
    assert lr_far >= base * 0.1 - 1e-9
