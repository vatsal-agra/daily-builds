"""Adam optimizer + LR schedule + gradient clipping, built directly on
Tensor.grad — no torch.optim, no framework."""
import math
import numpy as np


class Adam:
    def __init__(self, params, lr=3e-4, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.0):
        self.params = list(params)
        self.lr = lr
        self.b1, self.b2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.m = [np.zeros_like(p.data) for p in self.params]
        self.v = [np.zeros_like(p.data) for p in self.params]
        self.t = 0

    def zero_grad(self):
        for p in self.params:
            p.grad = None

    def clip_grad_norm(self, max_norm):
        total = 0.0
        for p in self.params:
            if p.grad is not None:
                total += float(np.sum(p.grad * p.grad))
        total = math.sqrt(total)
        if total > max_norm and total > 0:
            scale = max_norm / total
            for p in self.params:
                if p.grad is not None:
                    p.grad = p.grad * scale
        return total

    def step(self):
        self.t += 1
        for i, p in enumerate(self.params):
            if p.grad is None:
                continue
            g = p.grad
            if self.weight_decay:
                g = g + self.weight_decay * p.data
            self.m[i] = self.b1 * self.m[i] + (1 - self.b1) * g
            self.v[i] = self.b2 * self.v[i] + (1 - self.b2) * (g * g)
            mhat = self.m[i] / (1 - self.b1 ** self.t)
            vhat = self.v[i] / (1 - self.b2 ** self.t)
            p.data -= self.lr * mhat / (np.sqrt(vhat) + self.eps)


def lr_schedule(step, warmup_steps, total_steps, base_lr, min_lr_ratio=0.1):
    """Linear warmup then cosine decay to min_lr_ratio * base_lr."""
    if step < warmup_steps:
        return base_lr * (step + 1) / warmup_steps
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    progress = min(1.0, progress)
    cosine = 0.5 * (1 + math.cos(math.pi * progress))
    return base_lr * (min_lr_ratio + (1 - min_lr_ratio) * cosine)
