"""From-scratch reverse-mode automatic differentiation.

A minimal tensor-valued autograd engine in the spirit of Karpathy's
micrograd, generalized from scalars to numpy-backed n-dimensional arrays.
Every operator builds a node carrying a closure that knows how to push
gradients to its parents; ``Tensor.backward()`` walks the resulting graph
in reverse topological order. No autodiff library (autograd, PyTorch,
JAX, tinygrad) is used anywhere in this file — every backward pass below
is hand-derived.
"""
import numpy as np


def _unbroadcast(grad, shape):
    """Sum a gradient back down to ``shape`` after a numpy broadcast.

    Broadcasting silently duplicates values along new or size-1 axes on
    the forward pass; the backward pass must sum the incoming gradient
    back over exactly those axes to be consistent with the chain rule.
    """
    while grad.ndim > len(shape):
        grad = grad.sum(axis=0)
    for axis, dim in enumerate(shape):
        if dim == 1 and grad.shape[axis] != 1:
            grad = grad.sum(axis=axis, keepdims=True)
    return grad


def _as_tensor(x):
    return x if isinstance(x, Tensor) else Tensor(x, requires_grad=False)


def _accumulate(tensor, g):
    """Add gradient contribution ``g`` into ``tensor.grad``, allocating it
    lazily on first use. Most tensors in a feed-forward graph like this one
    receive exactly one contribution, so skipping the eager zeros_like
    allocation in __init__ (this used to run for every intermediate node,
    not just leaves) is a large, correctness-preserving speedup."""
    if tensor.grad is None:
        tensor.grad = g.copy()
    else:
        tensor.grad += g


class Tensor:
    __array_priority__ = 1000.0  # let Tensor win in numpy-vs-Tensor binops

    def __init__(self, data, children=(), requires_grad=True):
        self.data = np.asarray(data, dtype=np.float64)
        self.requires_grad = requires_grad
        self.grad = None  # allocated lazily by _accumulate() on first backward contribution
        self._children = children
        self._backward = lambda: None

    @property
    def shape(self):
        return self.data.shape

    @property
    def ndim(self):
        return self.data.ndim

    def zero_grad(self):
        if self.requires_grad:
            self.grad = None

    def backward(self, grad=None):
        topo, visited = [], set()

        def build(t):
            if id(t) not in visited:
                visited.add(id(t))
                for c in t._children:
                    build(c)
                topo.append(t)

        build(self)
        self.grad = np.ones_like(self.data) if grad is None else np.asarray(grad, dtype=np.float64)
        for t in reversed(topo):
            t._backward()

    # ---- elementwise arithmetic -------------------------------------
    def __add__(self, other):
        other = _as_tensor(other)
        out = Tensor(self.data + other.data, (self, other))

        def _backward():
            if self.requires_grad:
                _accumulate(self, _unbroadcast(out.grad, self.data.shape))
            if other.requires_grad:
                _accumulate(other, _unbroadcast(out.grad, other.data.shape))

        out._backward = _backward
        return out

    __radd__ = __add__

    def __neg__(self):
        out = Tensor(-self.data, (self,))

        def _backward():
            if self.requires_grad:
                _accumulate(self, -out.grad)

        out._backward = _backward
        return out

    def __sub__(self, other):
        return self + (-_as_tensor(other))

    def __rsub__(self, other):
        return _as_tensor(other) + (-self)

    def __mul__(self, other):
        other = _as_tensor(other)
        out = Tensor(self.data * other.data, (self, other))

        def _backward():
            if self.requires_grad:
                _accumulate(self, _unbroadcast(out.grad * other.data, self.data.shape))
            if other.requires_grad:
                _accumulate(other, _unbroadcast(out.grad * self.data, other.data.shape))

        out._backward = _backward
        return out

    __rmul__ = __mul__

    def __truediv__(self, other):
        return self * _as_tensor(other) ** -1.0

    def __pow__(self, p):
        assert isinstance(p, (int, float)), "only scalar exponents supported"
        out = Tensor(self.data ** p, (self,))

        def _backward():
            if self.requires_grad:
                _accumulate(self, out.grad * (p * self.data ** (p - 1)))

        out._backward = _backward
        return out

    # ---- matrix / shape ops -------------------------------------------
    def matmul(self, other):
        other = _as_tensor(other)
        out = Tensor(self.data @ other.data, (self, other))

        def _backward():
            if self.requires_grad:
                g = out.grad @ np.swapaxes(other.data, -1, -2)
                _accumulate(self, _unbroadcast(g, self.data.shape))
            if other.requires_grad:
                g = np.swapaxes(self.data, -1, -2) @ out.grad
                _accumulate(other, _unbroadcast(g, other.data.shape))

        out._backward = _backward
        return out

    __matmul__ = matmul

    def transpose(self, axis1, axis2):
        out = Tensor(np.swapaxes(self.data, axis1, axis2), (self,))

        def _backward():
            if self.requires_grad:
                _accumulate(self, np.swapaxes(out.grad, axis1, axis2))

        out._backward = _backward
        return out

    def reshape(self, *shape):
        if len(shape) == 1 and isinstance(shape[0], (tuple, list)):
            shape = tuple(shape[0])
        orig_shape = self.data.shape
        out = Tensor(self.data.reshape(shape), (self,))

        def _backward():
            if self.requires_grad:
                _accumulate(self, out.grad.reshape(orig_shape))

        out._backward = _backward
        return out

    def sum(self, axis=None, keepdims=False):
        out = Tensor(self.data.sum(axis=axis, keepdims=keepdims), (self,))
        in_shape = self.data.shape

        def _backward():
            if self.requires_grad:
                g = out.grad
                if not keepdims and axis is not None:
                    axes = (axis,) if isinstance(axis, int) else axis
                    g = np.expand_dims(g, axes)
                _accumulate(self, np.broadcast_to(g, in_shape))

        out._backward = _backward
        return out

    def mean(self, axis=None, keepdims=False):
        if axis is None:
            n = self.data.size
        else:
            axes = (axis,) if isinstance(axis, int) else axis
            n = 1
            for a in axes:
                n *= self.data.shape[a]
        return self.sum(axis=axis, keepdims=keepdims) * (1.0 / n)

    # ---- nonlinearities -------------------------------------------------
    def exp(self):
        out = Tensor(np.exp(self.data), (self,))

        def _backward():
            if self.requires_grad:
                _accumulate(self, out.grad * out.data)

        out._backward = _backward
        return out

    def log(self):
        out = Tensor(np.log(self.data), (self,))

        def _backward():
            if self.requires_grad:
                _accumulate(self, out.grad / self.data)

        out._backward = _backward
        return out

    def relu(self):
        out = Tensor(np.maximum(0.0, self.data), (self,))

        def _backward():
            if self.requires_grad:
                _accumulate(self, out.grad * (self.data > 0.0))

        out._backward = _backward
        return out

    def gelu(self):
        # GPT-2's tanh approximation of GELU (Hendrycks & Gimpel, 2016).
        c = np.sqrt(2.0 / np.pi)
        x = self.data
        u = c * (x + 0.044715 * x ** 3)
        t = np.tanh(u)
        out = Tensor(0.5 * x * (1.0 + t), (self,))

        def _backward():
            if self.requires_grad:
                du_dx = c * (1.0 + 3 * 0.044715 * x ** 2)
                dgelu_dx = 0.5 * (1.0 + t) + 0.5 * x * (1.0 - t ** 2) * du_dx
                _accumulate(self, out.grad * dgelu_dx)

        out._backward = _backward
        return out

    def softmax(self, axis=-1):
        x = self.data
        shifted = x - np.max(x, axis=axis, keepdims=True)
        ex = np.exp(shifted)
        probs = ex / np.sum(ex, axis=axis, keepdims=True)
        out = Tensor(probs, (self,))

        def _backward():
            if self.requires_grad:
                g = out.grad
                dot = np.sum(g * probs, axis=axis, keepdims=True)
                _accumulate(self, probs * (g - dot))

        out._backward = _backward
        return out

    def __getitem__(self, idx):
        out = Tensor(self.data[idx], (self,))
        in_shape = self.data.shape

        def _backward():
            if self.requires_grad:
                full = np.zeros(in_shape, dtype=np.float64)
                np.add.at(full, idx, out.grad)
                _accumulate(self, full)

        out._backward = _backward
        return out


def layer_norm(x: Tensor, gamma: Tensor, beta: Tensor, eps: float = 1e-5) -> Tensor:
    """LayerNorm over the last axis of ``x``, with a hand-derived backward pass."""
    d = x.data
    mu = d.mean(axis=-1, keepdims=True)
    xc = d - mu
    var = (xc ** 2).mean(axis=-1, keepdims=True)
    std = np.sqrt(var + eps)
    xhat = xc / std
    y = xhat * gamma.data + beta.data
    out = Tensor(y, (x, gamma, beta))
    D = d.shape[-1]

    def _backward():
        g = out.grad
        if gamma.requires_grad:
            axes = tuple(range(g.ndim - 1))
            _accumulate(gamma, (g * xhat).sum(axis=axes) if axes else (g * xhat))
        if beta.requires_grad:
            axes = tuple(range(g.ndim - 1))
            _accumulate(beta, g.sum(axis=axes) if axes else g)
        if x.requires_grad:
            dxhat = g * gamma.data
            dvar = np.sum(dxhat * xc * -0.5 * std ** -3, axis=-1, keepdims=True)
            dmu = np.sum(dxhat * -1.0 / std, axis=-1, keepdims=True) + dvar * np.sum(-2.0 * xc, axis=-1, keepdims=True) / D
            _accumulate(x, dxhat / std + dvar * 2.0 * xc / D + dmu / D)

    out._backward = _backward
    return out


def embedding(weight: Tensor, idx: np.ndarray) -> Tensor:
    """Row-gather lookup: ``out[...] = weight[idx[...]]``, scatter-add on backward."""
    idx = np.asarray(idx)
    out = Tensor(weight.data[idx], (weight,))

    def _backward():
        if weight.requires_grad:
            scattered = np.zeros_like(weight.data)
            np.add.at(scattered, idx, out.grad)
            _accumulate(weight, scattered)

    out._backward = _backward
    return out


def dropout(x: Tensor, p: float, training: bool) -> Tensor:
    if not training or p <= 0.0:
        return x
    mask = (np.random.rand(*x.data.shape) >= p).astype(np.float64) / (1.0 - p)
    out = Tensor(x.data * mask, (x,))

    def _backward():
        if x.requires_grad:
            _accumulate(x, out.grad * mask)

    out._backward = _backward
    return out


def cross_entropy(logits: Tensor, targets: np.ndarray) -> Tensor:
    """Mean softmax cross-entropy over the last axis, numerically stable.

    ``logits`` has shape (N, C); ``targets`` is an int array of shape (N,).
    """
    x = logits.data
    targets = np.asarray(targets)
    shifted = x - np.max(x, axis=-1, keepdims=True)
    logsumexp = np.log(np.sum(np.exp(shifted), axis=-1, keepdims=True))
    log_probs = shifted - logsumexp
    n = x.shape[0]
    picked = log_probs[np.arange(n), targets]
    loss_val = -np.mean(picked)
    out = Tensor(loss_val, (logits,))

    def _backward():
        if logits.requires_grad:
            probs = np.exp(log_probs)
            grad = probs.copy()
            grad[np.arange(n), targets] -= 1.0
            grad /= n
            _accumulate(logits, out.grad * grad)

    out._backward = _backward
    return out
