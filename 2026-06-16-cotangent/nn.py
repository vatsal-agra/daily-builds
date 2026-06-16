"""A tiny neural-network library built on the Cotangent autodiff engine.

Modules expose ``parameters()`` (a flat list of ``Value`` leaves) so optimizers
can update them and ``zero_grad`` can reset them. Initialization uses a seeded
PRNG for full determinism.
"""

from __future__ import annotations

import math
import random
from typing import Callable

from engine import Value

ACTIVATIONS: dict[str, Callable[[Value], Value]] = {
    "tanh": lambda v: v.tanh(),
    "relu": lambda v: v.relu(),
    "sigmoid": lambda v: v.sigmoid(),
    "linear": lambda v: v,
}


class Module:
    def parameters(self) -> list[Value]:
        return []

    def zero_grad(self) -> None:
        for p in self.parameters():
            p.grad = 0.0


class Neuron(Module):
    def __init__(self, n_in: int, activation: str = "tanh", rng: random.Random | None = None):
        rng = rng or random.Random(0)
        # Xavier/Glorot-ish init scaled by fan-in for stable training.
        scale = 1.0 / math.sqrt(n_in) if n_in > 0 else 1.0
        self.w = [Value(rng.uniform(-1, 1) * scale, label=f"w{i}") for i in range(n_in)]
        self.b = Value(0.0, label="b")
        if activation not in ACTIVATIONS:
            raise ValueError(f"unknown activation {activation!r}; "
                             f"choose from {sorted(ACTIVATIONS)}")
        self.activation = activation

    def __call__(self, x: list[Value]) -> Value:
        if len(x) != len(self.w):
            raise ValueError(f"expected {len(self.w)} inputs, got {len(x)}")
        act = self.b
        for wi, xi in zip(self.w, x):
            act = act + wi * xi
        return ACTIVATIONS[self.activation](act)

    def parameters(self) -> list[Value]:
        return self.w + [self.b]


class Layer(Module):
    def __init__(self, n_in: int, n_out: int, activation: str = "tanh",
                 rng: random.Random | None = None):
        rng = rng or random.Random(0)
        self.neurons = [Neuron(n_in, activation, rng) for _ in range(n_out)]

    def __call__(self, x: list[Value]) -> list[Value]:
        return [n(x) for n in self.neurons]

    def parameters(self) -> list[Value]:
        return [p for n in self.neurons for p in n.parameters()]


class MLP(Module):
    """Multi-layer perceptron.

    ``sizes`` is [n_in, h1, h2, ..., n_out]. Hidden layers use ``hidden_act``;
    the output layer uses ``out_act`` (default linear, so it pairs with a loss
    that applies its own sigmoid/softmax).
    """

    def __init__(self, sizes: list[int], hidden_act: str = "tanh",
                 out_act: str = "linear", seed: int = 0):
        if len(sizes) < 2:
            raise ValueError("need at least [n_in, n_out]")
        rng = random.Random(seed)
        self.layers: list[Layer] = []
        for i in range(len(sizes) - 1):
            act = hidden_act if i < len(sizes) - 2 else out_act
            self.layers.append(Layer(sizes[i], sizes[i + 1], act, rng))
        self.sizes = sizes

    def __call__(self, x: list[Value]) -> list[Value]:
        for layer in self.layers:
            x = layer(x)
        return x

    def parameters(self) -> list[Value]:
        return [p for layer in self.layers for p in layer.parameters()]

    def __repr__(self) -> str:
        return f"MLP(sizes={self.sizes}, params={len(self.parameters())})"
