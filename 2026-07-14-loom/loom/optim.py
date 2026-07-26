"""Adam optimizer and an LR warmup + cosine decay schedule, from scratch."""
import math

import numpy as np


class Adam:
    def __init__(self, params, lr=3e-4, betas=(0.9, 0.95), eps=1e-8, weight_decay=0.0):
        self.params = params
        self.lr = lr
        self.b1, self.b2 = betas
        self.eps = eps
        self.wd = weight_decay
        self.m = [np.zeros_like(p.value) for p in params]
        self.v = [np.zeros_like(p.value) for p in params]
        self.t = 0

    def step(self):
        self.t += 1
        b1t = 1 - self.b1 ** self.t
        b2t = 1 - self.b2 ** self.t
        for i, p in enumerate(self.params):
            g = p.grad
            if self.wd:
                g = g + self.wd * p.value
            self.m[i] = self.b1 * self.m[i] + (1 - self.b1) * g
            self.v[i] = self.b2 * self.v[i] + (1 - self.b2) * (g * g)
            mhat = self.m[i] / b1t
            vhat = self.v[i] / b2t
            p.value -= self.lr * mhat / (np.sqrt(vhat) + self.eps)

    def zero_grad(self):
        for p in self.params:
            p.zero_grad()


def clip_grad_norm(params, max_norm):
    total_sq = 0.0
    for p in params:
        total_sq += float(np.sum(p.grad ** 2))
    total_norm = math.sqrt(total_sq)
    if total_norm > max_norm and total_norm > 0:
        scale = max_norm / (total_norm + 1e-6)
        for p in params:
            p.grad *= scale
    return total_norm


def lr_schedule(step, warmup_steps, total_steps, max_lr, min_lr_ratio=0.1):
    """Linear warmup then cosine decay to `min_lr_ratio * max_lr`."""
    min_lr = max_lr * min_lr_ratio
    if step < warmup_steps:
        return max_lr * (step + 1) / max(1, warmup_steps)
    if step >= total_steps:
        return min_lr
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    coeff = 0.5 * (1.0 + math.cos(math.pi * progress))
    return min_lr + coeff * (max_lr - min_lr)
