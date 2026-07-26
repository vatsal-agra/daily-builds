"""Adam optimizer, from scratch (Kingma & Ba, 2014)."""
import numpy as np


class Adam:
    def __init__(self, params, lr=3e-3, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.0):
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

    def clip_grad_norm(self, max_norm):
        total_sq = 0.0
        for p in self.params:
            if p.grad is not None:
                total_sq += float(np.sum(p.grad ** 2))
        total_norm = total_sq ** 0.5
        if total_norm > max_norm > 0:
            scale = max_norm / (total_norm + 1e-6)
            for p in self.params:
                if p.grad is not None:
                    p.grad = p.grad * scale
        return total_norm

    def step(self):
        self.t += 1
        b1, b2 = self.beta1, self.beta2
        bc1 = 1 - b1 ** self.t
        bc2 = 1 - b2 ** self.t
        for i, p in enumerate(self.params):
            if p.grad is None:
                continue
            g = p.grad
            if self.weight_decay:
                g = g + self.weight_decay * p.data
            self.m[i] = b1 * self.m[i] + (1 - b1) * g
            self.v[i] = b2 * self.v[i] + (1 - b2) * (g * g)
            mhat = self.m[i] / bc1
            vhat = self.v[i] / bc2
            p.data = p.data - self.lr * mhat / (np.sqrt(vhat) + self.eps)
