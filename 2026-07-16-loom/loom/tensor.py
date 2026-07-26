"""A minimal reverse-mode autodiff engine over NumPy arrays.

Every operator below is a node in a computation graph: it produces a new
`Tensor` and attaches a `_backward` closure that knows how to route an
upstream gradient to its inputs. `Tensor.backward()` topologically sorts the
graph and calls each node's closure exactly once, in reverse order, so
gradients accumulate correctly even when a tensor is reused multiple times
(shared weights, residual connections, etc.).

No autograd library is used here (no PyTorch/JAX/autograd) -- this is the
whole engine, and every op is gradient-checked in `loom/gradcheck.py`.
"""
from __future__ import annotations

import numpy as np


def _unbroadcast(grad: np.ndarray, shape: tuple) -> np.ndarray:
    """Reduce `grad` (which may have extra/broadcast dims from a NumPy
    broadcasting op) back down to `shape` by summing over the axes that
    were broadcast."""
    while grad.ndim > len(shape):
        grad = grad.sum(axis=0)
    for axis, dim in enumerate(shape):
        if dim == 1 and grad.shape[axis] != 1:
            grad = grad.sum(axis=axis, keepdims=True)
    return grad


def _as_tensor(x) -> "Tensor":
    return x if isinstance(x, Tensor) else Tensor(x)


class Tensor:
    __slots__ = ("data", "grad", "requires_grad", "_children", "_backward", "_op")

    def __init__(self, data, requires_grad: bool = False, _children=(), _op: str = ""):
        self.data = np.asarray(data, dtype=np.float64)
        self.requires_grad = requires_grad
        self.grad = None
        self._children = _children
        self._backward = lambda: None
        self._op = _op

    @property
    def shape(self):
        return self.data.shape

    # ---- graph plumbing -------------------------------------------------
    def _accumulate(self, grad: np.ndarray) -> None:
        grad = _unbroadcast(grad, self.data.shape)
        self.grad = grad if self.grad is None else self.grad + grad

    def zero_grad(self) -> None:
        self.grad = None

    def detach(self) -> "Tensor":
        return Tensor(self.data.copy(), requires_grad=False)

    def backward(self, grad: np.ndarray | None = None) -> None:
        if grad is None:
            if self.data.size != 1:
                raise ValueError("backward() with no grad argument requires a scalar tensor")
            grad = np.ones_like(self.data)
        topo, visited = [], set()

        def build(node: "Tensor"):
            if id(node) not in visited:
                visited.add(id(node))
                for child in node._children:
                    build(child)
                topo.append(node)

        build(self)
        self.grad = grad if self.grad is None else self.grad + grad
        for node in reversed(topo):
            node._backward()

    # ---- elementwise ------------------------------------------------------
    def __add__(self, other):
        other = _as_tensor(other)
        out = Tensor(self.data + other.data, self.requires_grad or other.requires_grad,
                     (self, other), "+")

        def _backward():
            if self.requires_grad:
                self._accumulate(out.grad)
            if other.requires_grad:
                other._accumulate(out.grad)
        out._backward = _backward
        return out

    __radd__ = __add__

    def __neg__(self):
        out = Tensor(-self.data, self.requires_grad, (self,), "neg")

        def _backward():
            if self.requires_grad:
                self._accumulate(-out.grad)
        out._backward = _backward
        return out

    def __sub__(self, other):
        return self + (-_as_tensor(other))

    def __rsub__(self, other):
        return _as_tensor(other) + (-self)

    def __mul__(self, other):
        other = _as_tensor(other)
        out = Tensor(self.data * other.data, self.requires_grad or other.requires_grad,
                     (self, other), "*")

        def _backward():
            if self.requires_grad:
                self._accumulate(out.grad * other.data)
            if other.requires_grad:
                other._accumulate(out.grad * self.data)
        out._backward = _backward
        return out

    __rmul__ = __mul__

    def __pow__(self, p: float):
        out = Tensor(self.data ** p, self.requires_grad, (self,), f"**{p}")

        def _backward():
            if self.requires_grad:
                self._accumulate(out.grad * p * (self.data ** (p - 1)))
        out._backward = _backward
        return out

    def __truediv__(self, other):
        other = _as_tensor(other)
        return self * (other ** -1.0)

    def exp(self):
        e = np.exp(self.data)
        out = Tensor(e, self.requires_grad, (self,), "exp")

        def _backward():
            if self.requires_grad:
                self._accumulate(out.grad * e)
        out._backward = _backward
        return out

    def log(self):
        out = Tensor(np.log(self.data), self.requires_grad, (self,), "log")

        def _backward():
            if self.requires_grad:
                self._accumulate(out.grad / self.data)
        out._backward = _backward
        return out

    def tanh(self):
        t = np.tanh(self.data)
        out = Tensor(t, self.requires_grad, (self,), "tanh")

        def _backward():
            if self.requires_grad:
                self._accumulate(out.grad * (1.0 - t * t))
        out._backward = _backward
        return out

    # ---- reductions ---------------------------------------------------
    def sum(self, axis=None, keepdims=False):
        out = Tensor(self.data.sum(axis=axis, keepdims=keepdims), self.requires_grad,
                     (self,), "sum")

        def _backward():
            if self.requires_grad:
                g = out.grad
                if not keepdims and axis is not None:
                    g = np.expand_dims(g, axis if isinstance(axis, int) else axis)
                self._accumulate(np.broadcast_to(g, self.data.shape).copy())
        out._backward = _backward
        return out

    def mean(self, axis=None, keepdims=False):
        n = self.data.size if axis is None else (
            self.data.shape[axis] if isinstance(axis, int) else
            np.prod([self.data.shape[a] for a in axis]))
        return self.sum(axis=axis, keepdims=keepdims) * (1.0 / n)

    # ---- shape ops ------------------------------------------------------
    def reshape(self, *shape):
        if len(shape) == 1 and isinstance(shape[0], tuple):
            shape = shape[0]
        orig_shape = self.data.shape
        out = Tensor(self.data.reshape(shape), self.requires_grad, (self,), "reshape")

        def _backward():
            if self.requires_grad:
                self._accumulate(out.grad.reshape(orig_shape))
        out._backward = _backward
        return out

    def permute(self, *axes):
        if len(axes) == 1 and isinstance(axes[0], tuple):
            axes = axes[0]
        inv = np.argsort(axes)
        out = Tensor(np.transpose(self.data, axes), self.requires_grad, (self,), "permute")

        def _backward():
            if self.requires_grad:
                self._accumulate(np.transpose(out.grad, inv))
        out._backward = _backward
        return out

    def __matmul__(self, other):
        other = _as_tensor(other)
        out = Tensor(self.data @ other.data, self.requires_grad or other.requires_grad,
                     (self, other), "matmul")

        def _backward():
            if self.requires_grad:
                other_t = np.swapaxes(other.data, -1, -2)
                self._accumulate(out.grad @ other_t)
            if other.requires_grad:
                self_t = np.swapaxes(self.data, -1, -2)
                other._accumulate(self_t @ out.grad)
        out._backward = _backward
        return out

    def __repr__(self):
        return f"Tensor(shape={self.shape}, requires_grad={self.requires_grad})"


def embedding(weight: Tensor, idx: np.ndarray) -> Tensor:
    """Gather rows of `weight` (shape (V, d)) at integer positions `idx`
    (any int array shape), producing shape idx.shape + (d,)."""
    idx = np.asarray(idx)
    out = Tensor(weight.data[idx], weight.requires_grad, (weight,), "embedding")

    def _backward():
        if weight.requires_grad:
            g = np.zeros_like(weight.data)
            np.add.at(g, idx, out.grad)
            weight._accumulate(g)
    out._backward = _backward
    return out


def gather_rows(x: Tensor, idx: np.ndarray) -> Tensor:
    """x: (N, V) tensor, idx: (N,) int array -> out: (N,) tensor with
    out[i] = x[i, idx[i]]."""
    idx = np.asarray(idx)
    n = x.data.shape[0]
    rows = np.arange(n)
    out = Tensor(x.data[rows, idx], x.requires_grad, (x,), "gather_rows")

    def _backward():
        if x.requires_grad:
            g = np.zeros_like(x.data)
            g[rows, idx] = out.grad
            x._accumulate(g)
    out._backward = _backward
    return out


def softmax(x: Tensor, axis: int = -1) -> Tensor:
    shifted_data = x.data - np.max(x.data, axis=axis, keepdims=True)
    shifted = x + Tensor(shifted_data - x.data)  # stop-gradient constant shift
    exps = shifted.exp()
    denom = exps.sum(axis=axis, keepdims=True)
    return exps / denom


def layer_norm(x: Tensor, gamma: Tensor, beta: Tensor, eps: float = 1e-5) -> Tensor:
    mu = x.mean(axis=-1, keepdims=True)
    xmu = x - mu
    var = (xmu * xmu).mean(axis=-1, keepdims=True)
    std = (var + eps) ** 0.5
    xhat = xmu / std
    return xhat * gamma + beta


def gelu(x: Tensor) -> Tensor:
    """Tanh approximation of GELU (the one GPT-2 uses)."""
    c = (2.0 / np.pi) ** 0.5
    inner = (x + (x ** 3) * 0.044715) * c
    return x * 0.5 * (inner.tanh() + 1.0)


def cross_entropy(logits: Tensor, targets: np.ndarray) -> Tensor:
    """logits: (N, V) tensor, targets: (N,) int array -> scalar mean NLL loss."""
    probs = softmax(logits, axis=-1)
    log_probs = probs.log()
    picked = gather_rows(log_probs, targets)
    return -picked.mean()
