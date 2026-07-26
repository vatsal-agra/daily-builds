"""Adam optimizer and LR scheduling, written from scratch (no torch.optim)."""
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
                total += float((p.grad ** 2).sum())
        total = total ** 0.5
        if total > max_norm:
            scale = max_norm / (total + 1e-6)
            for p in self.params:
                if p.grad is not None:
                    p.grad *= scale
        return total

    def step(self, lr=None):
        lr = self.lr if lr is None else lr
        self.t += 1
        for i, p in enumerate(self.params):
            if p.grad is None:
                continue
            g = p.grad
            if self.weight_decay:
                g = g + self.weight_decay * p.data
            self.m[i] = self.b1 * self.m[i] + (1 - self.b1) * g
            self.v[i] = self.b2 * self.v[i] + (1 - self.b2) * (g ** 2)
            m_hat = self.m[i] / (1 - self.b1 ** self.t)
            v_hat = self.v[i] / (1 - self.b2 ** self.t)
            p.data -= lr * m_hat / (np.sqrt(v_hat) + self.eps)


def lr_schedule(step, warmup_steps, total_steps, base_lr, min_lr_ratio=0.1):
    """Linear warmup then cosine decay to min_lr_ratio * base_lr."""
    if step < warmup_steps:
        return base_lr * (step + 1) / max(1, warmup_steps)
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    progress = min(1.0, progress)
    cos = 0.5 * (1 + np.cos(np.pi * progress))
    min_lr = base_lr * min_lr_ratio
    return min_lr + (base_lr - min_lr) * cos
