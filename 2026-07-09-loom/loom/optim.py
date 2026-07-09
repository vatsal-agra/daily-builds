"""Adam, derived and coded from the original Kingma & Ba (2014) update rule
directly against `Tensor.grad` NumPy arrays -- no torch.optim anywhere."""
import math

import numpy as np


class Adam:
    def __init__(self, params, lr=3e-4, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.0):
        self.params = list(params)
        self.lr = lr
        self.b1, self.b2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.t = 0
        self.m = [np.zeros_like(p.data) for p in self.params]
        self.v = [np.zeros_like(p.data) for p in self.params]

    def zero_grad(self):
        for p in self.params:
            p.grad = np.zeros_like(p.data)

    def clip_grad_norm(self, max_norm):
        total = math.sqrt(sum(float(np.sum(p.grad ** 2)) for p in self.params))
        if total > max_norm:
            scale = max_norm / (total + 1e-6)
            for p in self.params:
                p.grad = p.grad * scale
        return total

    def step(self):
        self.t += 1
        b1t = 1.0 - self.b1 ** self.t
        b2t = 1.0 - self.b2 ** self.t
        for i, p in enumerate(self.params):
            g = p.grad
            if self.weight_decay:
                g = g + self.weight_decay * p.data
            self.m[i] = self.b1 * self.m[i] + (1.0 - self.b1) * g
            self.v[i] = self.b2 * self.v[i] + (1.0 - self.b2) * (g * g)
            mhat = self.m[i] / b1t
            vhat = self.v[i] / b2t
            p.data -= self.lr * mhat / (np.sqrt(vhat) + self.eps)

    def state_dict(self):
        return dict(t=self.t, m=[m.copy() for m in self.m], v=[v.copy() for v in self.v],
                    lr=self.lr, betas=(self.b1, self.b2), eps=self.eps, weight_decay=self.weight_decay)

    def load_state_dict(self, state):
        self.t = state["t"]
        self.m = [m.copy() for m in state["m"]]
        self.v = [v.copy() for v in state["v"]]
        self.lr = state["lr"]
        self.b1, self.b2 = state["betas"]
        self.eps = state["eps"]
        self.weight_decay = state["weight_decay"]
