"""A reverse-mode automatic-differentiation engine over NumPy tensors.

No ML framework is used anywhere in this file or anywhere downstream of it.
Every operation below is a "primitive": it computes a forward value and
registers a backward closure on the output node's autograd tape. Calling
``.backward()`` on a scalar walks the tape in reverse topological order and
accumulates gradients into every ``Tensor`` that requested one.

This mirrors the design of a minimal reverse-mode autodiff library (the
same shape as Karpathy's micrograd), except every node holds a NumPy array
instead of a Python float, which is what makes it fast enough to train a
multi-layer attention model instead of a toy scalar network.
"""

import numpy as np


def _unbroadcast(grad, shape):
    """Reduce ``grad`` (from a broadcasted op) back down to ``shape``.

    NumPy broadcasting can expand a smaller array in two ways: by adding
    leading dimensions, or by stretching an existing dimension of size 1.
    The backward pass has to undo both by summing over exactly the axes
    that were stretched.
    """
    while grad.ndim > len(shape):
        grad = grad.sum(axis=0)
    for axis, dim in enumerate(shape):
        if dim == 1 and grad.shape[axis] != 1:
            grad = grad.sum(axis=axis, keepdims=True)
    return grad


class Tensor:
    """A NumPy array with an autograd tape attached."""

    __slots__ = ("data", "grad", "requires_grad", "_backward", "_prev", "_op")

    def __init__(self, data, requires_grad=False, _children=(), _op=""):
        self.data = np.asarray(data, dtype=np.float64)
        self.grad = np.zeros_like(self.data) if requires_grad else None
        self.requires_grad = requires_grad
        self._backward = lambda: None
        self._prev = set(_children)
        self._op = _op

    # -- bookkeeping -----------------------------------------------------
    @property
    def shape(self):
        return self.data.shape

    def zero_grad(self):
        if self.requires_grad:
            self.grad = np.zeros_like(self.data)

    def item(self):
        return float(self.data)

    def __repr__(self):
        return f"Tensor(shape={self.data.shape}, op={self._op!r}, requires_grad={self.requires_grad})"

    def _wrap(self, other):
        return other if isinstance(other, Tensor) else Tensor(np.asarray(other, dtype=np.float64))

    # -- elementwise arithmetic -------------------------------------------
    def __add__(self, other):
        other = self._wrap(other)
        req = self.requires_grad or other.requires_grad
        out = Tensor(self.data + other.data, requires_grad=req, _children=(self, other), _op="add")

        def _backward():
            if self.requires_grad:
                self.grad += _unbroadcast(out.grad, self.data.shape)
            if other.requires_grad:
                other.grad += _unbroadcast(out.grad, other.data.shape)

        out._backward = _backward
        return out

    __radd__ = __add__

    def __neg__(self):
        out = Tensor(-self.data, requires_grad=self.requires_grad, _children=(self,), _op="neg")

        def _backward():
            if self.requires_grad:
                self.grad += -out.grad

        out._backward = _backward
        return out

    def __sub__(self, other):
        return self + (-self._wrap(other))

    def __rsub__(self, other):
        return self._wrap(other) + (-self)

    def __mul__(self, other):
        other = self._wrap(other)
        req = self.requires_grad or other.requires_grad
        out = Tensor(self.data * other.data, requires_grad=req, _children=(self, other), _op="mul")

        def _backward():
            if self.requires_grad:
                self.grad += _unbroadcast(out.grad * other.data, self.data.shape)
            if other.requires_grad:
                other.grad += _unbroadcast(out.grad * self.data, other.data.shape)

        out._backward = _backward
        return out

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = self._wrap(other)
        req = self.requires_grad or other.requires_grad
        out = Tensor(self.data / other.data, requires_grad=req, _children=(self, other), _op="div")

        def _backward():
            if self.requires_grad:
                self.grad += _unbroadcast(out.grad / other.data, self.data.shape)
            if other.requires_grad:
                other.grad += _unbroadcast(-out.grad * self.data / (other.data ** 2), other.data.shape)

        out._backward = _backward
        return out

    def __rtruediv__(self, other):
        return self._wrap(other) / self

    def __pow__(self, power):
        assert isinstance(power, (int, float)), "only constant exponents are supported"
        out = Tensor(self.data ** power, requires_grad=self.requires_grad, _children=(self,), _op=f"pow{power}")

        def _backward():
            if self.requires_grad:
                self.grad += out.grad * power * (self.data ** (power - 1))

        out._backward = _backward
        return out

    # -- matmul ------------------------------------------------------------
    def matmul(self, other):
        other = self._wrap(other)
        req = self.requires_grad or other.requires_grad
        out = Tensor(self.data @ other.data, requires_grad=req, _children=(self, other), _op="matmul")

        def _backward():
            if self.requires_grad:
                da = out.grad @ np.swapaxes(other.data, -1, -2)
                self.grad += _unbroadcast(da, self.data.shape)
            if other.requires_grad:
                db = np.swapaxes(self.data, -1, -2) @ out.grad
                other.grad += _unbroadcast(db, other.data.shape)

        out._backward = _backward
        return out

    def __matmul__(self, other):
        return self.matmul(other)

    # -- shape ops -----------------------------------------------------
    def reshape(self, *shape):
        if len(shape) == 1 and isinstance(shape[0], (tuple, list)):
            shape = tuple(shape[0])
        orig_shape = self.data.shape
        out = Tensor(self.data.reshape(shape), requires_grad=self.requires_grad, _children=(self,), _op="reshape")

        def _backward():
            if self.requires_grad:
                self.grad += out.grad.reshape(orig_shape)

        out._backward = _backward
        return out

    def transpose(self, *axes):
        if len(axes) == 1 and isinstance(axes[0], (tuple, list)):
            axes = tuple(axes[0])
        if not axes:
            axes = tuple(reversed(range(self.data.ndim)))
        inv = np.argsort(axes)
        out = Tensor(self.data.transpose(axes), requires_grad=self.requires_grad, _children=(self,), _op="transpose")

        def _backward():
            if self.requires_grad:
                self.grad += out.grad.transpose(tuple(inv))

        out._backward = _backward
        return out

    def __getitem__(self, idx):
        out = Tensor(self.data[idx], requires_grad=self.requires_grad, _children=(self,), _op="getitem")

        def _backward():
            if self.requires_grad:
                np.add.at(self.grad, idx, out.grad)

        out._backward = _backward
        return out

    # -- reductions -----------------------------------------------------
    def sum(self, axis=None, keepdims=False):
        out = Tensor(self.data.sum(axis=axis, keepdims=keepdims), requires_grad=self.requires_grad,
                     _children=(self,), _op="sum")

        def _backward():
            if self.requires_grad:
                g = out.grad
                if not keepdims and axis is not None:
                    g = np.expand_dims(g, axis=axis if isinstance(axis, int) else tuple(axis))
                self.grad += np.broadcast_to(g, self.data.shape)

        out._backward = _backward
        return out

    def mean(self, axis=None, keepdims=False):
        n = self.data.size if axis is None else (
            self.data.shape[axis] if isinstance(axis, int) else np.prod([self.data.shape[a] for a in axis])
        )
        return self.sum(axis=axis, keepdims=keepdims) * (1.0 / n)

    # -- elementwise transcendentals ------------------------------------
    def exp(self):
        e = np.exp(self.data)
        out = Tensor(e, requires_grad=self.requires_grad, _children=(self,), _op="exp")

        def _backward():
            if self.requires_grad:
                self.grad += out.grad * e

        out._backward = _backward
        return out

    def tanh(self):
        t = np.tanh(self.data)
        out = Tensor(t, requires_grad=self.requires_grad, _children=(self,), _op="tanh")

        def _backward():
            if self.requires_grad:
                self.grad += out.grad * (1.0 - t * t)

        out._backward = _backward
        return out

    def sqrt(self):
        r = np.sqrt(self.data)
        out = Tensor(r, requires_grad=self.requires_grad, _children=(self,), _op="sqrt")

        def _backward():
            if self.requires_grad:
                self.grad += out.grad * 0.5 / r

        out._backward = _backward
        return out

    def log(self):
        out = Tensor(np.log(self.data), requires_grad=self.requires_grad, _children=(self,), _op="log")

        def _backward():
            if self.requires_grad:
                self.grad += out.grad / self.data

        out._backward = _backward
        return out

    # -- backward pass ----------------------------------------------------
    def backward(self):
        assert self.data.shape == () or self.data.size == 1, "backward() requires a scalar output"
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


def cat(tensors, axis=0):
    """Concatenate tensors along ``axis`` (used by the KV-cache)."""
    req = any(t.requires_grad for t in tensors)
    datas = [t.data for t in tensors]
    out = Tensor(np.concatenate(datas, axis=axis), requires_grad=req, _children=tuple(tensors), _op="cat")
    sizes = [d.shape[axis] for d in datas]

    def _backward():
        offset = 0
        for t, size in zip(tensors, sizes):
            if t.requires_grad:
                sl = [slice(None)] * out.data.ndim
                sl[axis] = slice(offset, offset + size)
                t.grad += out.grad[tuple(sl)]
            offset += size

    out._backward = _backward
    return out


def softmax(x, axis=-1):
    shifted = x.data - x.data.max(axis=axis, keepdims=True)
    e = np.exp(shifted)
    s = e / e.sum(axis=axis, keepdims=True)
    out = Tensor(s, requires_grad=x.requires_grad, _children=(x,), _op="softmax")

    def _backward():
        if x.requires_grad:
            dy = out.grad
            dot = (dy * s).sum(axis=axis, keepdims=True)
            x.grad += s * (dy - dot)

    out._backward = _backward
    return out


def layer_norm(x, gamma, beta, eps=1e-5):
    """LayerNorm over the last axis of ``x``, scaled/shifted by (gamma, beta)."""
    D = x.data.shape[-1]
    mu = x.data.mean(axis=-1, keepdims=True)
    var = x.data.var(axis=-1, keepdims=True)
    inv_std = 1.0 / np.sqrt(var + eps)
    xhat = (x.data - mu) * inv_std
    out_data = xhat * gamma.data + beta.data
    req = x.requires_grad or gamma.requires_grad or beta.requires_grad
    out = Tensor(out_data, requires_grad=req, _children=(x, gamma, beta), _op="layernorm")

    def _backward():
        dy = out.grad
        if gamma.requires_grad:
            reduce_axes = tuple(range(dy.ndim - 1))
            gamma.grad += (dy * xhat).sum(axis=reduce_axes) if reduce_axes else (dy * xhat)
        if beta.requires_grad:
            reduce_axes = tuple(range(dy.ndim - 1))
            beta.grad += dy.sum(axis=reduce_axes) if reduce_axes else dy
        if x.requires_grad:
            dxhat = dy * gamma.data
            term1 = D * dxhat
            term2 = dxhat.sum(axis=-1, keepdims=True)
            term3 = xhat * (dxhat * xhat).sum(axis=-1, keepdims=True)
            x.grad += (inv_std / D) * (term1 - term2 - term3)

    out._backward = _backward
    return out


_GELU_C = np.sqrt(2.0 / np.pi)


def gelu(x):
    """Tanh-approximate GELU activation (the same formula GPT-2 uses)."""
    xd = x.data
    inner = _GELU_C * (xd + 0.044715 * xd ** 3)
    t = np.tanh(inner)
    out_data = 0.5 * xd * (1.0 + t)
    out = Tensor(out_data, requires_grad=x.requires_grad, _children=(x,), _op="gelu")

    def _backward():
        if x.requires_grad:
            dinner_dx = _GELU_C * (1.0 + 3.0 * 0.044715 * xd ** 2)
            dgelu_dx = 0.5 * (1.0 + t) + 0.5 * xd * (1.0 - t * t) * dinner_dx
            x.grad += out.grad * dgelu_dx

    out._backward = _backward
    return out


def masked_fill(x, mask, value):
    """Fill ``x`` with ``value`` wherever the boolean NumPy array ``mask`` is True."""
    out_data = np.where(mask, value, x.data)
    out = Tensor(out_data, requires_grad=x.requires_grad, _children=(x,), _op="masked_fill")

    def _backward():
        if x.requires_grad:
            x.grad += np.where(mask, 0.0, out.grad)

    out._backward = _backward
    return out


def embedding_lookup(table, indices):
    """Gather rows of a (V, D) embedding ``table`` (a Tensor) at ``indices`` (an int ndarray)."""
    indices = np.asarray(indices)
    out_data = table.data[indices]
    out = Tensor(out_data, requires_grad=table.requires_grad, _children=(table,), _op="embedding")

    def _backward():
        if table.requires_grad:
            np.add.at(table.grad, indices, out.grad)

    out._backward = _backward
    return out


def cross_entropy(logits, targets):
    """Mean softmax cross-entropy loss. ``logits``: Tensor (N, V). ``targets``: int ndarray (N,)."""
    xd = logits.data
    shifted = xd - xd.max(axis=-1, keepdims=True)
    e = np.exp(shifted)
    probs = e / e.sum(axis=-1, keepdims=True)
    N = xd.shape[0]
    targets = np.asarray(targets)
    correct_logp = np.log(np.clip(probs[np.arange(N), targets], 1e-12, None))
    loss_val = -correct_logp.mean()
    out = Tensor(loss_val, requires_grad=True, _children=(logits,), _op="cross_entropy")

    def _backward():
        dlogits = probs.copy()
        dlogits[np.arange(N), targets] -= 1.0
        dlogits *= (out.grad / N)
        logits.grad += dlogits

    out._backward = _backward
    return out


class Parameter(Tensor):
    """A Tensor that always requires grad — a learnable weight."""

    def __init__(self, data):
        super().__init__(data, requires_grad=True)
