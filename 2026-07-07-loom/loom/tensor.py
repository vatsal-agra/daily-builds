"""A from-scratch reverse-mode autograd engine over NumPy arrays.

NumPy is used purely as an array/BLAS substrate (the same role a
hand-rolled matrix library would play) - every gradient here is derived
by a computational graph this module builds and walks itself. No
autograd library (PyTorch/JAX/autograd/etc.) is used anywhere.
"""
import numpy as np

_grad_enabled = True


class no_grad:
    """Context manager for pure inference (mirrors torch.no_grad()). Ops
    still compute their forward value but skip building _children/_backward,
    so no graph - and no reference cycle - is created at all. Use this for
    forward passes that will never have .backward() called on them (model
    evaluation, autoregressive sampling): it is both faster (no closures
    allocated) and the deeper fix for the reference-cycle memory behavior
    noted below, not just a bigger hammer for gc.collect() to swing."""

    def __enter__(self):
        global _grad_enabled
        self._prev = _grad_enabled
        _grad_enabled = False
        return self

    def __exit__(self, *exc):
        global _grad_enabled
        _grad_enabled = self._prev
        return False


def _unbroadcast(grad, shape):
    """Reduce `grad` (which may have extra/broadcast dims from a numpy
    broadcasting op) down to `shape` by summing over the axes that were
    broadcast. Mirrors numpy's own broadcasting rules in reverse."""
    while grad.ndim > len(shape):
        grad = grad.sum(axis=0)
    for axis, dim in enumerate(shape):
        if dim == 1 and grad.shape[axis] != 1:
            grad = grad.sum(axis=axis, keepdims=True)
    return grad


class Tensor:
    __slots__ = ("data", "requires_grad", "grad", "_backward", "_prev", "_op")

    def __init__(self, data, requires_grad=False, _children=(), _op=""):
        self.data = np.asarray(data, dtype=np.float64)
        self.requires_grad = requires_grad
        self.grad = None
        self._backward = lambda: None
        self._prev = _children
        self._op = _op

    # -- construction helpers --------------------------------------------
    @staticmethod
    def _coerce(x):
        return x if isinstance(x, Tensor) else Tensor(x, requires_grad=False)

    @property
    def shape(self):
        return self.data.shape

    @property
    def ndim(self):
        return self.data.ndim

    def item(self):
        return float(self.data)

    def _ensure_grad(self):
        if self.grad is None:
            self.grad = np.zeros_like(self.data)

    def zero_grad(self):
        # None (not a zero array) so Adam.step()'s `if p.grad is None: skip`
        # keeps working the same way regardless of which zero_grad a caller
        # reaches for - Tensor.zero_grad(), Module.zero_grad(), or
        # Adam.zero_grad() are now one convention, not two.
        self.grad = None

    def __repr__(self):
        return f"Tensor(shape={self.data.shape}, requires_grad={self.requires_grad})"

    # -- elementwise ops ---------------------------------------------------
    def __add__(self, other):
        other = Tensor._coerce(other)
        data = self.data + other.data
        if not _grad_enabled:
            return Tensor(data)
        req = self.requires_grad or other.requires_grad
        out = Tensor(data, requires_grad=req, _children=(self, other), _op="add")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                self.grad += _unbroadcast(out.grad, self.data.shape)
            if other.requires_grad:
                other._ensure_grad()
                other.grad += _unbroadcast(out.grad, other.data.shape)
        out._backward = _backward
        return out

    __radd__ = __add__

    def __neg__(self):
        data = -self.data
        if not _grad_enabled:
            return Tensor(data)
        out = Tensor(data, requires_grad=self.requires_grad, _children=(self,), _op="neg")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                self.grad += -out.grad
        out._backward = _backward
        return out

    def __sub__(self, other):
        return self + (-Tensor._coerce(other))

    def __rsub__(self, other):
        return Tensor._coerce(other) + (-self)

    def __mul__(self, other):
        other = Tensor._coerce(other)
        data = self.data * other.data
        if not _grad_enabled:
            return Tensor(data)
        req = self.requires_grad or other.requires_grad
        out = Tensor(data, requires_grad=req, _children=(self, other), _op="mul")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                self.grad += _unbroadcast(out.grad * other.data, self.data.shape)
            if other.requires_grad:
                other._ensure_grad()
                other.grad += _unbroadcast(out.grad * self.data, other.data.shape)
        out._backward = _backward
        return out

    __rmul__ = __mul__

    def __pow__(self, p):
        assert isinstance(p, (int, float)), "only scalar exponents supported"
        data = self.data ** p
        if not _grad_enabled:
            return Tensor(data)
        out = Tensor(data, requires_grad=self.requires_grad, _children=(self,), _op=f"pow{p}")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                self.grad += (p * self.data ** (p - 1)) * out.grad
        out._backward = _backward
        return out

    def __truediv__(self, other):
        other = Tensor._coerce(other)
        return self * other ** -1

    def __rtruediv__(self, other):
        return Tensor._coerce(other) * self ** -1

    # -- reductions ---------------------------------------------------------
    def sum(self, axis=None, keepdims=False):
        data = self.data.sum(axis=axis, keepdims=keepdims)
        if not _grad_enabled:
            return Tensor(data)
        out = Tensor(data, requires_grad=self.requires_grad, _children=(self,), _op="sum")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                g = out.grad
                if axis is not None and not keepdims:
                    g = np.expand_dims(g, axis if isinstance(axis, int) else tuple(axis))
                self.grad += np.ones_like(self.data) * g
        out._backward = _backward
        return out

    def mean(self, axis=None, keepdims=False):
        n = self.data.size if axis is None else (
            self.data.shape[axis] if isinstance(axis, int)
            else np.prod([self.data.shape[a] for a in axis]))
        return self.sum(axis=axis, keepdims=keepdims) * (1.0 / n)

    # -- shape ops ------------------------------------------------------------
    def reshape(self, *shape):
        if len(shape) == 1 and isinstance(shape[0], (tuple, list)):
            shape = tuple(shape[0])
        data = self.data.reshape(*shape)
        if not _grad_enabled:
            return Tensor(data)
        out = Tensor(data, requires_grad=self.requires_grad, _children=(self,), _op="reshape")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                self.grad += out.grad.reshape(self.data.shape)
        out._backward = _backward
        return out

    def transpose(self, *axes):
        if len(axes) == 1 and isinstance(axes[0], (tuple, list)):
            axes = tuple(axes[0])
        data = self.data.transpose(*axes)
        if not _grad_enabled:
            return Tensor(data)
        out = Tensor(data, requires_grad=self.requires_grad, _children=(self,), _op="transpose")
        # Normalize to non-negative axes before inverting the permutation -
        # np.argsort on raw axes (e.g. (0, -1, 1)) sorts by literal value,
        # not by position, and silently computes the wrong inverse whenever
        # an axis list mixes negative and positive indices.
        axes_norm = [a % self.ndim for a in axes]
        inv = np.argsort(axes_norm)

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                self.grad += out.grad.transpose(*inv)
        out._backward = _backward
        return out

    def __getitem__(self, idx):
        data = self.data[idx]
        if not _grad_enabled:
            return Tensor(data)
        out = Tensor(data, requires_grad=self.requires_grad, _children=(self,), _op="getitem")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                np.add.at(self.grad, idx, out.grad)
        out._backward = _backward
        return out

    # -- matmul ---------------------------------------------------------------
    def matmul(self, other):
        other = Tensor._coerce(other)
        data = np.matmul(self.data, other.data)
        if not _grad_enabled:
            return Tensor(data)
        req = self.requires_grad or other.requires_grad
        out = Tensor(data, requires_grad=req, _children=(self, other), _op="matmul")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                bT = np.swapaxes(other.data, -1, -2)
                self.grad += _unbroadcast(np.matmul(out.grad, bT), self.data.shape)
            if other.requires_grad:
                other._ensure_grad()
                aT = np.swapaxes(self.data, -1, -2)
                other.grad += _unbroadcast(np.matmul(aT, out.grad), other.data.shape)
        out._backward = _backward
        return out

    def __matmul__(self, other):
        return self.matmul(other)

    # -- unary math -------------------------------------------------------------
    def exp(self):
        data = np.exp(self.data)
        if not _grad_enabled:
            return Tensor(data)
        out = Tensor(data, requires_grad=self.requires_grad, _children=(self,), _op="exp")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                self.grad += out.data * out.grad
        out._backward = _backward
        return out

    def log(self):
        data = np.log(self.data)
        if not _grad_enabled:
            return Tensor(data)
        out = Tensor(data, requires_grad=self.requires_grad, _children=(self,), _op="log")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                self.grad += out.grad / self.data
        out._backward = _backward
        return out

    def tanh(self):
        t = np.tanh(self.data)
        if not _grad_enabled:
            return Tensor(t)
        out = Tensor(t, requires_grad=self.requires_grad, _children=(self,), _op="tanh")

        def _backward():
            if self.requires_grad:
                self._ensure_grad()
                self.grad += (1 - t ** 2) * out.grad
        out._backward = _backward
        return out

    def sqrt(self):
        return self ** 0.5

    # -- concatenation (static) ---------------------------------------------------
    @staticmethod
    def cat(tensors, axis=-1):
        tensors = [Tensor._coerce(t) for t in tensors]
        data = np.concatenate([t.data for t in tensors], axis=axis)
        if not _grad_enabled:
            return Tensor(data)
        req = any(t.requires_grad for t in tensors)
        out = Tensor(data, requires_grad=req, _children=tuple(tensors), _op="cat")
        sizes = [t.data.shape[axis] for t in tensors]

        def _backward():
            splits = np.split(out.grad, np.cumsum(sizes)[:-1], axis=axis)
            for t, g in zip(tensors, splits):
                if t.requires_grad:
                    t._ensure_grad()
                    t.grad += g
        out._backward = _backward
        return out

    # -- backward -------------------------------------------------------------------
    def backward(self, grad=None):
        if grad is None:
            assert self.data.size == 1, "backward() with no grad requires a scalar output"
            grad = np.ones_like(self.data)

        topo, visited = [], set()

        def build(v):
            if id(v) not in visited:
                visited.add(id(v))
                for child in v._prev:
                    build(child)
                topo.append(v)
        build(self)

        self.grad = np.asarray(grad, dtype=np.float64)
        for v in reversed(topo):
            v._backward()
