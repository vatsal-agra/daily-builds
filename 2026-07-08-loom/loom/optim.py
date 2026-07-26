"""Hand-written Adam optimizer, LR schedule, and gradient clipping."""
import math

import numpy as np


class Adam:
    def __init__(self, params, lr=3e-4, betas=(0.9, 0.95), eps=1e-8, weight_decay=0.0):
        self.params = list(params)
        self.lr = lr
        self.beta1, self.beta2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.m = [np.zeros_like(p.data) for p in self.params]
        self.v = [np.zeros_like(p.data) for p in self.params]
        self.t = 0

    def zero_grad(self):
        for p in self.params:
            p.grad = None

    def step(self):
        self.t += 1
        for i, p in enumerate(self.params):
            if p.grad is None:
                continue
            g = p.grad
            if self.weight_decay:
                g = g + self.weight_decay * p.data
            self.m[i] = self.beta1 * self.m[i] + (1 - self.beta1) * g
            self.v[i] = self.beta2 * self.v[i] + (1 - self.beta2) * (g * g)
            m_hat = self.m[i] / (1 - self.beta1 ** self.t)
            v_hat = self.v[i] / (1 - self.beta2 ** self.t)
            p.data -= self.lr * m_hat / (np.sqrt(v_hat) + self.eps)


def clip_grad_norm(params, max_norm):
    """Global-norm gradient clipping across all params. Returns the
    (unclipped) total norm."""
    total_sq = 0.0
    for p in params:
        if p.grad is not None:
            total_sq += float(np.sum(p.grad ** 2))
    total_norm = math.sqrt(total_sq)
    if total_norm > max_norm and total_norm > 0:
        scale = max_norm / (total_norm + 1e-6)
        for p in params:
            if p.grad is not None:
                p.grad *= scale
    return total_norm


def lr_schedule(step, warmup_steps, total_steps, base_lr, min_lr_ratio=0.1):
    """Linear warmup then cosine decay to `min_lr_ratio * base_lr`."""
    if step < warmup_steps:
        return base_lr * (step + 1) / max(1, warmup_steps)
    if step >= total_steps:
        return base_lr * min_lr_ratio
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    coeff = 0.5 * (1.0 + math.cos(math.pi * progress))
    return base_lr * (min_lr_ratio + (1 - min_lr_ratio) * coeff)
