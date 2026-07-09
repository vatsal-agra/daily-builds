"""
A reverse-mode autograd engine over NumPy arrays.

This is the entire gradient story for the rest of Loom: every op below
builds a small piece of a dynamic computation graph (a `Tensor` node plus
a `_backward` closure that knows how to push a gradient from its output
back to its inputs), and `Tensor.backward()` walks that graph in reverse
topological order accumulating gradients. NumPy is used purely as a dense
array/BLAS library here -- there is no autograd, no `requires_grad`
machinery, no optimizer anywhere else in NumPy or this codebase except
what is written in this file and `optim.py`.

The one subtlety that makes tensor-shaped autograd harder than
scalar-shaped autograd (see e.g. a scalar `Value` graph) is broadcasting:
NumPy silently broadcasts `(3,4) + (4,)` to `(3,4)`, so the backward pass
has to know how to *undo* that broadcast -- sum the incoming gradient back
down to the original, smaller shape. `Tensor._unbroadcast` is that inverse
operation and every binary op below routes its gradients through it.
"""
import math
import numpy as np


def _pow(x, power):
    """x ** power via exponentiation by squaring for integer powers.

    NumPy's own `**` falls back to a slow generic ufunc path for integer
    exponents outside {-1, 0, 1, 2} on some builds (measured >50x slower
    than plain multiplication for exponent 3 -- exactly the exponent GELU
    uses), so every integer power in this engine's hot path goes through
    here instead of `x ** power` directly.
    """
    if isinstance(power, float) and not power.is_integer():
        return x ** power
    n = int(power)
    if n == 0:
        return np.ones_like(x)
    neg, n = n < 0, abs(n)
    result, base = np.ones_like(x), x
    while n:
        if n & 1:
            result = result * base
        n >>= 1
        if n:
            base = base * base
    return (1.0 / result) if neg else result


class Tensor:
    __slots__ = ("data", "requires_grad", "grad", "_backward", "_prev", "_op")

    def __init__(self, data, requires_grad=False, _children=(), _op=""):
        self.data = np.asarray(data, dtype=np.float64)
        self.requires_grad = requires_grad
        self.grad = np.zeros_like(self.data) if requires_grad else None
        self._backward = lambda: None
        self._prev = set(_children)
        self._op = _op

    # -- basic properties -------------------------------------------------
    @property
    def shape(self):
        return self.data.shape

    @property
    def ndim(self):
        return self.data.ndim

    def item(self):
        return float(self.data)

    def zero_grad(self):
        if self.requires_grad:
            self.grad = np.zeros_like(self.data)

    def __repr__(self):
        return f"Tensor(shape={self.shape}, requires_grad={self.requires_grad}, op={self._op!r})"

    @staticmethod
    def _as_tensor(x):
        return x if isinstance(x, Tensor) else Tensor(x)

    @staticmethod
    def _unbroadcast(grad, shape):
        """Sum-reduce `grad` down to `shape`, undoing NumPy broadcasting."""
        while grad.ndim > len(shape):
            grad = grad.sum(axis=0)
        for axis, size in enumerate(shape):
            if size == 1 and grad.shape[axis] != 1:
                grad = grad.sum(axis=axis, keepdims=True)
        return grad.reshape(shape)

    # -- graph traversal / backward ---------------------------------------
    def backward(self):
        topo = []
        visited = set()

        def build(v):
            if id(v) not in visited:
                visited.add(id(v))
                for child in v._prev:
                    build(child)
                topo.append(v)

        build(self)
        self.grad = np.ones_like(self.data)
        for v in reversed(topo):
            v._backward()

    # -- elementwise binary ops --------------------------------------------
    def __add__(self, other):
        other = self._as_tensor(other)
        requires_grad = self.requires_grad or other.requires_grad
        out = Tensor(self.data + other.data, requires_grad, (self, other), "+")

        def _backward():
            if self.requires_grad:
                self.grad += self._unbroadcast(out.grad, self.data.shape)
            if other.requires_grad:
                other.grad += self._unbroadcast(out.grad, other.data.shape)

        out._backward = _backward
        return out

    __radd__ = __add__

    def __neg__(self):
        out = Tensor(-self.data, self.requires_grad, (self,), "neg")

        def _backward():
            if self.requires_grad:
                self.grad += self._unbroadcast(-out.grad, self.data.shape)

        out._backward = _backward
        return out

    def __sub__(self, other):
        return self + (-self._as_tensor(other))

    def __rsub__(self, other):
        return self._as_tensor(other) + (-self)

    def __mul__(self, other):
        other = self._as_tensor(other)
        requires_grad = self.requires_grad or other.requires_grad
        out = Tensor(self.data * other.data, requires_grad, (self, other), "*")

        def _backward():
            if self.requires_grad:
                self.grad += self._unbroadcast(out.grad * other.data, self.data.shape)
            if other.requires_grad:
                other.grad += self._unbroadcast(out.grad * self.data, other.data.shape)

        out._backward = _backward
        return out

    __rmul__ = __mul__

    def __pow__(self, power):
        assert isinstance(power, (int, float)), "Tensor ** Tensor is not supported"
        out = Tensor(_pow(self.data, power), self.requires_grad, (self,), f"**{power}")

        def _backward():
            if self.requires_grad:
                if power == 0:
                    deriv = np.zeros_like(self.data)
                else:
                    deriv = power * _pow(self.data, power - 1)
                self.grad += deriv * out.grad

        out._backward = _backward
        return out

    def __truediv__(self, other):
        other = self._as_tensor(other)
        return self * (other ** -1)

    def __rtruediv__(self, other):
        return self._as_tensor(other) * (self ** -1)

    # -- matrix multiply (batched, broadcasting-aware) ----------------------
    def __matmul__(self, other):
        other = self._as_tensor(other)
        requires_grad = self.requires_grad or other.requires_grad
        out = Tensor(self.data @ other.data, requires_grad, (self, other), "@")

        def _backward():
            if self.requires_grad:
                grad_self = out.grad @ np.swapaxes(other.data, -1, -2)
                self.grad += self._unbroadcast(grad_self, self.data.shape)
            if other.requires_grad:
                grad_other = np.swapaxes(self.data, -1, -2) @ out.grad
                other.grad += self._unbroadcast(grad_other, other.data.shape)

        out._backward = _backward
        return out

    # -- reductions ----------------------------------------------------------
    def sum(self, axis=None, keepdims=False):
        out = Tensor(self.data.sum(axis=axis, keepdims=keepdims), self.requires_grad, (self,), "sum")
        in_shape = self.data.shape

        def _backward():
            if not self.requires_grad:
                return
            g = out.grad
            if axis is not None and not keepdims:
                ax = (axis,) if isinstance(axis, int) else tuple(axis)
                g = np.expand_dims(g, ax)
            self.grad += np.broadcast_to(g, in_shape)

        out._backward = _backward
        return out

    def mean(self, axis=None, keepdims=False):
        if axis is None:
            n = self.data.size
        else:
            ax = (axis,) if isinstance(axis, int) else tuple(axis)
            n = 1
            for a in ax:
                n *= self.data.shape[a]
        return self.sum(axis=axis, keepdims=keepdims) * (1.0 / n)

    # -- elementwise unary ops -------------------------------------------
    def exp(self):
        out_data = np.exp(self.data)
        out = Tensor(out_data, self.requires_grad, (self,), "exp")

        def _backward():
            if self.requires_grad:
                self.grad += out_data * out.grad

        out._backward = _backward
        return out

    def log(self):
        out = Tensor(np.log(self.data), self.requires_grad, (self,), "log")

        def _backward():
            if self.requires_grad:
                self.grad += (1.0 / self.data) * out.grad

        out._backward = _backward
        return out

    def sqrt(self):
        out_data = np.sqrt(self.data)
        out = Tensor(out_data, self.requires_grad, (self,), "sqrt")

        def _backward():
            if self.requires_grad:
                self.grad += (0.5 / out_data) * out.grad

        out._backward = _backward
        return out

    def tanh(self):
        t = np.tanh(self.data)
        out = Tensor(t, self.requires_grad, (self,), "tanh")

        def _backward():
            if self.requires_grad:
                self.grad += (1.0 - t * t) * out.grad

        out._backward = _backward
        return out

    def relu(self):
        out_data = np.maximum(self.data, 0.0)
        out = Tensor(out_data, self.requires_grad, (self,), "relu")

        def _backward():
            if self.requires_grad:
                self.grad += (self.data > 0.0) * out.grad

        out._backward = _backward
        return out

    # -- shape ops ------------------------------------------------------
    def reshape(self, *shape):
        if len(shape) == 1 and isinstance(shape[0], (tuple, list)):
            shape = tuple(shape[0])
        out = Tensor(self.data.reshape(shape), self.requires_grad, (self,), "reshape")
        in_shape = self.data.shape

        def _backward():
            if self.requires_grad:
                self.grad += out.grad.reshape(in_shape)

        out._backward = _backward
        return out

    def transpose(self, *axes):
        if len(axes) == 0:
            axes = tuple(reversed(range(self.data.ndim)))
        elif len(axes) == 1 and isinstance(axes[0], (tuple, list)):
            axes = tuple(axes[0])
        out = Tensor(np.transpose(self.data, axes), self.requires_grad, (self,), "transpose")
        inv = tuple(np.argsort(axes))

        def _backward():
            if self.requires_grad:
                self.grad += np.transpose(out.grad, inv)

        out._backward = _backward
        return out

    def __getitem__(self, idx):
        out = Tensor(self.data[idx], self.requires_grad, (self,), "getitem")

        def _backward():
            if self.requires_grad:
                g = np.zeros_like(self.data)
                np.add.at(g, idx, out.grad)
                self.grad += g

        out._backward = _backward
        return out

    def masked_fill(self, mask, value):
        """`mask` is a plain (non-Tensor) boolean NumPy array, broadcastable
        to this tensor's shape. Positions where `mask` is True are replaced
        by `value`; gradient does not flow through those positions."""
        out_data = np.where(mask, value, self.data)
        out = Tensor(out_data, self.requires_grad, (self,), "masked_fill")

        def _backward():
            if self.requires_grad:
                self.grad += np.where(mask, 0.0, out.grad)

        out._backward = _backward
        return out

    # -- softmax family ----------------------------------------------------
    def softmax(self, axis=-1):
        x = self.data - np.max(self.data, axis=axis, keepdims=True)
        e = np.exp(x)
        s = e / np.sum(e, axis=axis, keepdims=True)
        out = Tensor(s, self.requires_grad, (self,), "softmax")

        def _backward():
            if self.requires_grad:
                g = out.grad
                dot = np.sum(g * s, axis=axis, keepdims=True)
                self.grad += s * (g - dot)

        out._backward = _backward
        return out

    def log_softmax(self, axis=-1):
        x = self.data
        m = np.max(x, axis=axis, keepdims=True)
        shifted = x - m
        lse = np.log(np.sum(np.exp(shifted), axis=axis, keepdims=True))
        out_data = shifted - lse
        out = Tensor(out_data, self.requires_grad, (self,), "log_softmax")

        def _backward():
            if self.requires_grad:
                g = out.grad
                s = np.exp(out_data)  # = softmax(x)
                self.grad += g - s * np.sum(g, axis=axis, keepdims=True)

        out._backward = _backward
        return out


def cat(tensors, axis=0):
    tensors = list(tensors)
    requires_grad = any(t.requires_grad for t in tensors)
    datas = [t.data for t in tensors]
    out = Tensor(np.concatenate(datas, axis=axis), requires_grad, tuple(tensors), "cat")
    sizes = [d.shape[axis] for d in datas]

    def _backward():
        splits = np.split(out.grad, np.cumsum(sizes)[:-1], axis=axis)
        for t, g in zip(tensors, splits):
            if t.requires_grad:
                t.grad += g

    out._backward = _backward
    return out


def gelu(x):
    """Tanh-approximation GELU, built entirely out of Tensor primitives so
    its backward pass is free -- no hand-derived GELU gradient needed."""
    c = math.sqrt(2.0 / math.pi)
    inner = (x + (x ** 3) * 0.044715) * c
    return x * (inner.tanh() * 0.5 + 0.5)


def cross_entropy(logits, targets):
    """logits: Tensor (N, V). targets: int array (N,) of class indices.
    Returns a scalar Tensor -- mean negative log-likelihood."""
    targets = np.asarray(targets)
    n = logits.shape[0]
    logp = logits.log_softmax(axis=-1)
    picked = logp[np.arange(n), targets]  # (N,)
    return -picked.mean()
