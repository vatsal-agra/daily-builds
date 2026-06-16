"""Cotangent — reverse-mode automatic differentiation engine.

A ``Value`` is a scalar node in a computation DAG. Each operation builds a new
node, records its inputs (``_prev``) and a local ``_backward`` closure that knows
how to push the node's cotangent (``grad``) onto its inputs via the chain rule.

Calling ``.backward()`` on a node seeds its gradient with 1.0 and walks the graph
in reverse topological order, so every node's ``_backward`` runs only after the
node has accumulated the full cotangent from all of its consumers.

Pure Python, no dependencies.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable


class Value:
    """A differentiable scalar.

    Supports + - * / ** and unary -, plus exp/log/relu/tanh/sigmoid. Gradients
    accumulate (``+=``) so expressions that reuse a node — ``x * x`` or ``x + x``
    — are handled correctly.
    """

    __slots__ = ("data", "grad", "_backward", "_prev", "_op", "label")

    def __init__(self, data: float, _children: Iterable["Value"] = (), _op: str = "",
                 label: str = ""):
        self.data: float = float(data)
        self.grad: float = 0.0
        self._backward: Callable[[], None] = lambda: None
        self._prev: tuple["Value", ...] = tuple(_children)
        self._op: str = _op
        self.label: str = label

    # ---- helpers -----------------------------------------------------------
    @staticmethod
    def _coerce(other) -> "Value":
        return other if isinstance(other, Value) else Value(other)

    # ---- core ops ----------------------------------------------------------
    def __add__(self, other) -> "Value":
        other = self._coerce(other)
        out = Value(self.data + other.data, (self, other), "+")

        def _backward():
            self.grad += out.grad
            other.grad += out.grad
        out._backward = _backward
        return out

    def __mul__(self, other) -> "Value":
        other = self._coerce(other)
        out = Value(self.data * other.data, (self, other), "*")

        def _backward():
            self.grad += other.data * out.grad
            other.grad += self.data * out.grad
        out._backward = _backward
        return out

    def __pow__(self, other) -> "Value":
        # Supports Value ** (int/float constant). General a**b is added separately
        # via exp/log composition if a base is a Value.
        if isinstance(other, Value):
            # a ** b  =  exp(b * log(a))   (requires a > 0)
            if self.data <= 0:
                raise ValueError(
                    f"Value ** Value requires a positive base, got base={self.data}")
            return (other * self.log()).exp()
        out = Value(self.data ** other, (self,), f"**{other}")

        def _backward():
            self.grad += (other * self.data ** (other - 1)) * out.grad
        out._backward = _backward
        return out

    def relu(self) -> "Value":
        out = Value(self.data if self.data > 0 else 0.0, (self,), "relu")

        def _backward():
            self.grad += (1.0 if self.data > 0 else 0.0) * out.grad
        out._backward = _backward
        return out

    def tanh(self) -> "Value":
        t = math.tanh(self.data)
        out = Value(t, (self,), "tanh")

        def _backward():
            self.grad += (1.0 - t * t) * out.grad
        out._backward = _backward
        return out

    def sigmoid(self) -> "Value":
        # numerically stable logistic
        x = self.data
        if x >= 0:
            s = 1.0 / (1.0 + math.exp(-x))
        else:
            ex = math.exp(x)
            s = ex / (1.0 + ex)
        out = Value(s, (self,), "sigmoid")

        def _backward():
            self.grad += (s * (1.0 - s)) * out.grad
        out._backward = _backward
        return out

    def exp(self) -> "Value":
        e = math.exp(self.data)
        out = Value(e, (self,), "exp")

        def _backward():
            self.grad += e * out.grad
        out._backward = _backward
        return out

    def log(self) -> "Value":
        if self.data <= 0:
            raise ValueError(
                f"log() domain error: log of non-positive value {self.data}")
        out = Value(math.log(self.data), (self,), "log")

        def _backward():
            self.grad += (1.0 / self.data) * out.grad
        out._backward = _backward
        return out

    # ---- composed / dunder sugar ------------------------------------------
    def __neg__(self) -> "Value":
        return self * -1.0

    def __radd__(self, other) -> "Value":
        return self + other

    def __sub__(self, other) -> "Value":
        return self + (-self._coerce(other))

    def __rsub__(self, other) -> "Value":
        return self._coerce(other) + (-self)

    def __rmul__(self, other) -> "Value":
        return self * other

    def __truediv__(self, other) -> "Value":
        return self * self._coerce(other) ** -1.0

    def __rtruediv__(self, other) -> "Value":
        return self._coerce(other) * self ** -1.0

    # ---- backprop ----------------------------------------------------------
    def backward(self) -> None:
        """Reverse-mode pass: seed grad=1 here, propagate to all ancestors."""
        topo: list[Value] = []
        visited: set[int] = set()

        def build(v: "Value"):
            if id(v) not in visited:
                visited.add(id(v))
                for child in v._prev:
                    build(child)
                topo.append(v)

        build(self)
        # zero every grad reachable from here, then seed and propagate.
        for v in topo:
            v.grad = 0.0
        self.grad = 1.0
        for v in reversed(topo):
            v._backward()

    def topo(self) -> list["Value"]:
        """Return all nodes in this graph in topological (input→output) order."""
        order: list[Value] = []
        visited: set[int] = set()

        def build(v: "Value"):
            if id(v) not in visited:
                visited.add(id(v))
                for child in v._prev:
                    build(child)
                order.append(v)

        build(self)
        return order

    # ---- misc --------------------------------------------------------------
    def __repr__(self) -> str:
        lab = f"{self.label}=" if self.label else ""
        return f"Value({lab}data={self.data:.4f}, grad={self.grad:.4f})"
