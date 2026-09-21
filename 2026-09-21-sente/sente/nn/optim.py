"""Hand-rolled Adam optimizer (Kingma & Ba, 2014). No framework, no
`torch.optim` -- per-parameter first/second raw moment estimates with
bias correction, updated in place on each layer's parameter arrays.
"""

from __future__ import annotations
import numpy as np


class Adam:
    def __init__(self, layers, lr=1e-3, beta1=0.9, beta2=0.999, eps=1e-8):
        self.layers = layers
        self.lr = lr
        self.beta1 = beta1
        self.beta2 = beta2
        self.eps = eps
        self.t = 0
        self.m = {}
        self.v = {}
        for i, layer in enumerate(layers):
            for name, p in layer.params().items():
                key = (i, name)
                self.m[key] = np.zeros_like(p)
                self.v[key] = np.zeros_like(p)

    def step(self):
        self.t += 1
        b1, b2, eps, lr = self.beta1, self.beta2, self.eps, self.lr
        bias1 = 1.0 - b1 ** self.t
        bias2 = 1.0 - b2 ** self.t
        for i, layer in enumerate(self.layers):
            params = layer.params()
            grads = layer.grads()
            for name, p in params.items():
                g = grads[name]
                key = (i, name)
                self.m[key] = b1 * self.m[key] + (1 - b1) * g
                self.v[key] = b2 * self.v[key] + (1 - b2) * (g * g)
                mhat = self.m[key] / bias1
                vhat = self.v[key] / bias2
                p -= lr * mhat / (np.sqrt(vhat) + eps)
                # p is mutated in place; but numpy `-=` on a view works only
                # if `p` really is the same array object the layer holds.
                # Linear.W/.b are plain attributes, so this is safe: no
                # copy is made anywhere between params() and here.
                #
                # No zero_grad() here: every Layer.backward() call
                # assigns a brand-new dW/db array from scratch (see
                # Linear.backward) rather than accumulating into an
                # existing one, so there is nothing to zero between
                # steps -- an earlier version of this file had a
                # zero_grad() method that was dead code for exactly that
                # reason (removed in the Phase 3 review).
