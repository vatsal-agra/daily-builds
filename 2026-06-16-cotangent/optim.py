"""Optimizers for Cotangent parameters.

An optimizer holds a reference to a flat list of ``Value`` parameters and updates
their ``.data`` in place from their ``.grad`` after a backward pass.
"""

from __future__ import annotations

from engine import Value


class Optimizer:
    def __init__(self, params: list[Value], lr: float):
        self.params = list(params)
        self.lr = lr

    def zero_grad(self) -> None:
        for p in self.params:
            p.grad = 0.0

    def step(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class SGD(Optimizer):
    """SGD with optional momentum and (decoupled) weight decay."""

    def __init__(self, params: list[Value], lr: float = 0.05,
                 momentum: float = 0.0, weight_decay: float = 0.0):
        super().__init__(params, lr)
        self.momentum = momentum
        self.weight_decay = weight_decay
        self.velocity = [0.0] * len(self.params)

    def step(self) -> None:
        for i, p in enumerate(self.params):
            g = p.grad + self.weight_decay * p.data
            self.velocity[i] = self.momentum * self.velocity[i] + g
            p.data -= self.lr * self.velocity[i]


class Adam(Optimizer):
    """Adam optimizer (Kingma & Ba, 2015) with bias correction."""

    def __init__(self, params: list[Value], lr: float = 0.01,
                 betas: tuple[float, float] = (0.9, 0.999), eps: float = 1e-8,
                 weight_decay: float = 0.0):
        super().__init__(params, lr)
        self.b1, self.b2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.m = [0.0] * len(self.params)
        self.v = [0.0] * len(self.params)
        self.t = 0

    def step(self) -> None:
        self.t += 1
        for i, p in enumerate(self.params):
            g = p.grad + self.weight_decay * p.data
            self.m[i] = self.b1 * self.m[i] + (1 - self.b1) * g
            self.v[i] = self.b2 * self.v[i] + (1 - self.b2) * g * g
            m_hat = self.m[i] / (1 - self.b1 ** self.t)
            v_hat = self.v[i] / (1 - self.b2 ** self.t)
            p.data -= self.lr * m_hat / (v_hat ** 0.5 + self.eps)
