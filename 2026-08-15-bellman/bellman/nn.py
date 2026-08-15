"""A tiny multilayer perceptron built on the scalar autodiff engine.

Used as the REINFORCE policy network: continuous state in, action-preference
logits out. No matrix library — every weight is an individual `Value`
scalar, every forward pass builds the graph `autodiff.backward()` walks.
"""
import random

from .autodiff import Value


class Linear:
    """A fully-connected layer: y = W x + b, all entries are autodiff Values."""

    def __init__(self, n_in, n_out, rng):
        # Small random init scaled by fan-in (a from-scratch Xavier-ish init).
        scale = (1.0 / n_in) ** 0.5
        self.W = [[Value(rng.uniform(-scale, scale)) for _ in range(n_in)]
                  for _ in range(n_out)]
        self.b = [Value(0.0) for _ in range(n_out)]
        self.n_in, self.n_out = n_in, n_out

    def __call__(self, x):
        assert len(x) == self.n_in, f"expected {self.n_in} inputs, got {len(x)}"
        out = []
        for row, bias in zip(self.W, self.b):
            acc = bias
            for w, xi in zip(row, x):
                acc = acc + w * xi
            out.append(acc)
        return out

    def parameters(self):
        return [w for row in self.W for w in row] + self.b


class MLP:
    """Linear -> relu -> ... -> Linear stack. `sizes` includes input & output dims."""

    def __init__(self, sizes, seed=0):
        rng = random.Random(seed)
        self.layers = [Linear(sizes[i], sizes[i + 1], rng) for i in range(len(sizes) - 1)]

    def __call__(self, x):
        for i, layer in enumerate(self.layers):
            x = layer(x)
            if i < len(self.layers) - 1:
                x = [v.relu() for v in x]
        return x

    def parameters(self):
        return [p for layer in self.layers for p in layer.parameters()]

    def zero_grad(self):
        for p in self.parameters():
            p.grad = 0.0

    def state_dict(self):
        """Plain-float snapshot of every weight, for JSON export to the HTML viz."""
        return {
            "sizes": [self.layers[0].n_in] + [l.n_out for l in self.layers],
            "layers": [
                {"W": [[w.data for w in row] for row in layer.W],
                 "b": [b.data for b in layer.b]}
                for layer in self.layers
            ],
        }
