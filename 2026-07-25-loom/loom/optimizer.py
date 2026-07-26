"""
Adam optimizer (decoupled weight decay, i.e. AdamW), global-norm gradient
clipping, and a warmup + cosine-decay learning-rate schedule. All from
scratch — no `scipy`, no framework optimizer.
"""
import math

import numpy as np


class AdamW:
    def __init__(self, params, lr=3e-4, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01):
        """params: dict[name -> np.ndarray] (arrays are mutated in place)."""
        self.params = params
        self.lr = lr
        self.beta1, self.beta2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.m = {k: np.zeros_like(v) for k, v in params.items()}
        self.v = {k: np.zeros_like(v) for k, v in params.items()}
        self.t = 0

    def step(self, grads, lr=None):
        lr = self.lr if lr is None else lr
        self.t += 1
        bc1 = 1 - self.beta1 ** self.t
        bc2 = 1 - self.beta2 ** self.t
        for name, p in self.params.items():
            g = grads[name]
            if self.weight_decay > 0.0 and not name.endswith(".b") and "beta" not in name and "gamma" not in name:
                p -= lr * self.weight_decay * p
            m = self.m[name]
            v = self.v[name]
            m *= self.beta1
            m += (1 - self.beta1) * g
            v *= self.beta2
            v += (1 - self.beta2) * (g * g)
            mhat = m / bc1
            vhat = v / bc2
            p -= lr * mhat / (np.sqrt(vhat) + self.eps)


def clip_grad_global_norm(grads, max_norm):
    total_sq = 0.0
    for g in grads.values():
        total_sq += float(np.sum(g * g))
    total_norm = math.sqrt(total_sq)
    if not math.isfinite(total_norm):
        # NaN/Inf compares False to everything, including `> max_norm` below —
        # without this check a diverged training run would silently skip
        # clipping and feed NaN straight into AdamW instead of failing loudly.
        bad = [name for name, g in grads.items() if not np.all(np.isfinite(g))]
        raise FloatingPointError(
            f"non-finite gradient (norm={total_norm}) in: {bad[:5]}"
            f"{'...' if len(bad) > 5 else ''} — training has diverged, likely from"
            f" too high a learning rate."
        )
    if total_norm > max_norm and total_norm > 0:
        scale = max_norm / (total_norm + 1e-6)
        for g in grads.values():
            g *= scale
    return total_norm


def warmup_cosine_lr(step, warmup_steps, total_steps, base_lr, min_lr_ratio=0.1):
    if step < warmup_steps:
        return base_lr * (step + 1) / max(warmup_steps, 1)
    if step >= total_steps:
        return base_lr * min_lr_ratio
    progress = (step - warmup_steps) / max(total_steps - warmup_steps, 1)
    coeff = 0.5 * (1.0 + math.cos(math.pi * progress))
    return min_lr_ratio * base_lr + coeff * (base_lr - min_lr_ratio * base_lr)
