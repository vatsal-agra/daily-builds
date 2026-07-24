"""Adam (Kingma & Ba, 2014), implemented from scratch over loom.engine.Tensor
gradients. No torch.optim / no framework optimizer."""
import numpy as np


class Adam:
    def __init__(self, params, lr=3e-4, betas=(0.9, 0.95), eps=1e-8, weight_decay=0.0):
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
            p.zero_grad()

    def step(self):
        self.t += 1
        for i, p in enumerate(self.params):
            g = p.grad
            # Decoupled (AdamW-style) weight decay, applied only to matrices
            # (ndim >= 2: embeddings, attention/MLP weights). Biases and
            # LayerNorm gain/shift are 1D and conventionally excluded --
            # decaying a LayerNorm gain toward 0 fights the normalization
            # it's there to provide.
            if self.weight_decay > 0.0 and p.data.ndim >= 2:
                p.data -= self.lr * self.weight_decay * p.data
            self.m[i] = self.b1 * self.m[i] + (1 - self.b1) * g
            self.v[i] = self.b2 * self.v[i] + (1 - self.b2) * (g * g)
            mhat = self.m[i] / (1 - self.b1 ** self.t)
            vhat = self.v[i] / (1 - self.b2 ** self.t)
            p.data -= self.lr * mhat / (np.sqrt(vhat) + self.eps)
