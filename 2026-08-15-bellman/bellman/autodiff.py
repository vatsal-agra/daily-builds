"""A from-scratch scalar reverse-mode autodiff engine.

Every REINFORCE policy in this project is trained through this module —
no PyTorch/TensorFlow/JAX/autograd. Each `Value` is one node in a dynamic
computation graph; `backward()` walks it in reverse topological order and
accumulates gradients via the chain rule, exactly the algorithm behind
every modern deep-learning framework's autodiff core.
"""
import math


class Value:
    """A scalar node in a computation graph, tracking its own gradient."""

    __slots__ = ("data", "grad", "_backward", "_prev", "_op")

    def __init__(self, data, _children=(), _op=""):
        self.data = float(data)
        self.grad = 0.0
        self._backward = lambda: None
        self._prev = set(_children)
        self._op = _op

    def __repr__(self):
        return f"Value(data={self.data:.6f}, grad={self.grad:.6f})"

    @staticmethod
    def _wrap(x):
        return x if isinstance(x, Value) else Value(x)

    def __add__(self, other):
        other = Value._wrap(other)
        out = Value(self.data + other.data, (self, other), "+")

        def _backward():
            self.grad += out.grad
            other.grad += out.grad
        out._backward = _backward
        return out

    __radd__ = __add__

    def __mul__(self, other):
        other = Value._wrap(other)
        out = Value(self.data * other.data, (self, other), "*")

        def _backward():
            self.grad += other.data * out.grad
            other.grad += self.data * out.grad
        out._backward = _backward
        return out

    __rmul__ = __mul__

    def __neg__(self):
        return self * -1.0

    def __sub__(self, other):
        return self + (-Value._wrap(other))

    def __rsub__(self, other):
        return Value._wrap(other) + (-self)

    def __pow__(self, p):
        assert isinstance(p, (int, float)), "only numeric powers are supported"
        out = Value(self.data ** p, (self,), f"**{p}")

        def _backward():
            self.grad += (p * self.data ** (p - 1)) * out.grad
        out._backward = _backward
        return out

    def __truediv__(self, other):
        other = Value._wrap(other)
        return self * other ** -1

    def __rtruediv__(self, other):
        return Value._wrap(other) * self ** -1

    def exp(self):
        e = math.exp(min(self.data, 60.0))  # clip to avoid float overflow
        out = Value(e, (self,), "exp")

        def _backward():
            self.grad += e * out.grad
        out._backward = _backward
        return out

    def log(self):
        eps = 1e-12
        out = Value(math.log(max(self.data, eps)), (self,), "log")

        def _backward():
            self.grad += (1.0 / max(self.data, eps)) * out.grad
        out._backward = _backward
        return out

    def tanh(self):
        t = math.tanh(self.data)
        out = Value(t, (self,), "tanh")

        def _backward():
            self.grad += (1 - t * t) * out.grad
        out._backward = _backward
        return out

    def relu(self):
        out = Value(self.data if self.data > 0 else 0.0, (self,), "relu")

        def _backward():
            self.grad += (out.data > 0) * out.grad
        out._backward = _backward
        return out

    def backward(self):
        # Iterative post-order DFS topological sort -- NOT recursive. A
        # REINFORCE episode's loss graph is one long left-associative chain
        # of additions (one term per timestep), so a naive recursive
        # `build(child)` walk recurses as deep as the episode is long, and a
        # few hundred timesteps is enough to blow Python's default ~1000
        # call-stack recursion limit (verified: a 2000-step episode crashes
        # with RecursionError under the recursive version). An explicit
        # stack has no such ceiling.
        topo = []
        visited = set()
        stack = [(self, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                topo.append(node)
                continue
            if id(node) in visited:
                continue
            visited.add(id(node))
            stack.append((node, True))
            for child in node._prev:
                if id(child) not in visited:
                    stack.append((child, False))

        self.grad = 1.0
        for v in reversed(topo):
            v._backward()


def softmax(values):
    """Numerically-stable softmax over a list of Value logits -> list of Value probs."""
    m = max(v.data for v in values)
    shifted = [v - m for v in values]
    exps = [v.exp() for v in shifted]
    total = exps[0]
    for e in exps[1:]:
        total = total + e
    return [e / total for e in exps]
