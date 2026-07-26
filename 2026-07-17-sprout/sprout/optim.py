"""Adam optimizer, implemented from scratch (Kingma & Ba, 2014)."""
import numpy as np


class Adam:
    def __init__(self, model, lr=3e-4, betas=(0.9, 0.95), eps=1e-8, weight_decay=0.0):
        self.model = model
        self.lr = lr
        self.b1, self.b2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.t = 0
        self.m = {}
        self.v = {}
        for name, p, _ in model.parameters():
            self.m[name] = np.zeros_like(p)
            self.v[name] = np.zeros_like(p)

    def step(self, clip_norm=1.0):
        self.t += 1
        if clip_norm is not None:
            total_sq = 0.0
            for _, _, g in self.model.parameters():
                total_sq += float(np.sum(g * g))
            total_norm = np.sqrt(total_sq)
            if total_norm > clip_norm:
                scale = clip_norm / (total_norm + 1e-6)
                for _, _, g in self.model.parameters():
                    g *= scale

        for name, p, g in self.model.parameters():
            if self.weight_decay > 0.0 and p.ndim >= 2:
                g = g + self.weight_decay * p
            self.m[name] = self.b1 * self.m[name] + (1 - self.b1) * g
            self.v[name] = self.b2 * self.v[name] + (1 - self.b2) * (g * g)
            mhat = self.m[name] / (1 - self.b1**self.t)
            vhat = self.v[name] / (1 - self.b2**self.t)
            p -= self.lr * mhat / (np.sqrt(vhat) + self.eps)
