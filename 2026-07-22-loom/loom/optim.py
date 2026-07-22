"""Adam optimizer, implemented from scratch (Kingma & Ba, 2015)."""

import numpy as np


class Adam:
    def __init__(self, params, lr=3e-4, betas=(0.9, 0.95), eps=1e-8, weight_decay=0.0):
        self.params = list(params)
        self.lr = lr
        self.beta1, self.beta2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.t = 0
        self.m = [np.zeros_like(p.data) for p in self.params]
        self.v = [np.zeros_like(p.data) for p in self.params]

    def zero_grad(self):
        for p in self.params:
            p.zero_grad()

    def step(self, lr=None):
        lr = self.lr if lr is None else lr
        self.t += 1
        bc1 = 1.0 - self.beta1 ** self.t
        bc2 = 1.0 - self.beta2 ** self.t
        for i, p in enumerate(self.params):
            if p.grad is None:
                continue
            g = p.grad
            if self.weight_decay:
                g = g + self.weight_decay * p.data
            self.m[i] = self.beta1 * self.m[i] + (1 - self.beta1) * g
            self.v[i] = self.beta2 * self.v[i] + (1 - self.beta2) * (g * g)
            m_hat = self.m[i] / bc1
            v_hat = self.v[i] / bc2
            p.data -= lr * m_hat / (np.sqrt(v_hat) + self.eps)


def lr_schedule(step, warmup_steps, total_steps, base_lr, min_lr_ratio=0.1):
    """Linear warmup then cosine decay to ``min_lr_ratio * base_lr``."""
    if step < warmup_steps:
        return base_lr * (step + 1) / warmup_steps
    if step >= total_steps:
        return base_lr * min_lr_ratio
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    cosine = 0.5 * (1.0 + np.cos(np.pi * progress))
    return base_lr * (min_lr_ratio + (1.0 - min_lr_ratio) * cosine)
