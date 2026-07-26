"""Adam optimizer, LR warmup+cosine schedule, and gradient clipping -- all
operating directly on the `Tensor` parameters produced by loom/model.py.
"""
from __future__ import annotations

import math
import numpy as np

from loom.tensor import Tensor


class Adam:
    def __init__(self, params: list[Tensor], lr: float = 3e-4, betas=(0.9, 0.999),
                 eps: float = 1e-8, weight_decay: float = 0.0):
        self.params = params
        self.lr = lr
        self.b1, self.b2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.t = 0
        self.m = [np.zeros_like(p.data) for p in params]
        self.v = [np.zeros_like(p.data) for p in params]

    def zero_grad(self) -> None:
        for p in self.params:
            p.zero_grad()

    def step(self, lr: float | None = None) -> None:
        lr = self.lr if lr is None else lr
        self.t += 1
        for i, p in enumerate(self.params):
            if p.grad is None:
                continue
            g = p.grad
            if self.weight_decay:
                g = g + self.weight_decay * p.data
            self.m[i] = self.b1 * self.m[i] + (1 - self.b1) * g
            self.v[i] = self.b2 * self.v[i] + (1 - self.b2) * (g * g)
            m_hat = self.m[i] / (1 - self.b1 ** self.t)
            v_hat = self.v[i] / (1 - self.b2 ** self.t)
            p.data = p.data - lr * m_hat / (np.sqrt(v_hat) + self.eps)


def grad_global_norm(params: list[Tensor]) -> float:
    total = 0.0
    for p in params:
        if p.grad is not None:
            total += float(np.sum(p.grad ** 2))
    return math.sqrt(total)


def clip_grad_norm(params: list[Tensor], max_norm: float) -> float:
    norm = grad_global_norm(params)
    if norm > max_norm > 0:
        scale = max_norm / (norm + 1e-6)
        for p in params:
            if p.grad is not None:
                p.grad = p.grad * scale
    return norm


def lr_schedule(step: int, base_lr: float, warmup_steps: int, total_steps: int,
                 min_lr_ratio: float = 0.1) -> float:
    """Linear warmup, then cosine decay down to `min_lr_ratio * base_lr`."""
    if step < warmup_steps:
        return base_lr * (step + 1) / max(1, warmup_steps)
    if total_steps <= warmup_steps:
        return base_lr
    progress = (step - warmup_steps) / (total_steps - warmup_steps)
    progress = min(1.0, max(0.0, progress))
    coeff = 0.5 * (1.0 + math.cos(math.pi * progress))
    min_lr = base_lr * min_lr_ratio
    return min_lr + coeff * (base_lr - min_lr)
