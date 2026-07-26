"""A from-scratch reverse-mode autograd engine over NumPy arrays.

NumPy supplies dense-array storage and BLAS matmul only; every gradient rule
below (broadcasting reduction, matmul, softmax, cross-entropy, embedding
scatter-add, etc.) is hand-derived and hand-written. No autodiff or neural
network framework (PyTorch/TensorFlow/JAX/etc.) is used anywhere.
"""
import numpy as np

_GRAD_ENABLED = True


class no_grad:
    """Context manager that disables graph-building (for inference)."""

    def __enter__(self):
        global _GRAD_ENABLED
        self._prev = _GRAD_ENABLED
        _GRAD_ENABLED = False
        return self

    def __exit__(self, *exc):
        global _GRAD_ENABLED
        _GRAD_ENABLED = self._prev
        return False


def is_grad_enabled():
    return _GRAD_ENABLED


def _unbroadcast(grad, shape):
    """Reduce `grad` (numpy array, possibly broadcast-expanded) down to `shape`
    by summing over the axes NumPy broadcasting would have expanded."""
    while grad.ndim > len(shape):
        grad = grad.sum(axis=0)
    for i, dim in enumerate(shape):
        if dim == 1 and grad.shape[i] != 1:
            grad = grad.sum(axis=i, keepdims=True)
    return grad


def _as_tensor(x):
    return x if isinstance(x, Tensor) else Tensor(x)


class Tensor:
    __array_priority__ = 1000  # let Tensor win in numpy-vs-Tensor binary ops

    def __init__(self, data, requires_grad=False, _children=(), _op=""):
        self.data = np.asarray(data, dtype=np.float64)
        self.requires_grad = requires_grad and _GRAD_ENABLED
        self.grad = None
        self._backward = lambda: None
        self._prev = _children if _GRAD_ENABLED else ()
        self._op = _op

    @property
    def shape(self):
        return self.data.shape

    @property
    def ndim(self):
        return self.data.ndim

    def zero_grad(self):
        self.grad = np.zeros_like(self.data)

    # ---- graph construction helper -----------------------------------
    def _make_out(self, data, children, op, backward_fn):
        req = _GRAD_ENABLED and any(
            isinstance(c, Tensor) and c.requires_grad for c in children
        )
        out = Tensor(data, requires_grad=req, _children=tuple(children) if req else (), _op=op)
        if req:
            out._backward = backward_fn
        return out

    # ---- elementwise arithmetic ---------------------------------------
    def __add__(self, other):
        other = _as_tensor(other)
        out = self._make_out(self.data + other.data, (self, other), "+", None)

        def _backward():
            if self.requires_grad:
                self.grad += _unbroadcast(out.grad, self.data.shape)
            if other.requires_grad:
                other.grad += _unbroadcast(out.grad, other.data.shape)

        out._backward = _backward
        return out

    __radd__ = __add__

    def __neg__(self):
        out = self._make_out(-self.data, (self,), "neg", None)

        def _backward():
            if self.requires_grad:
                self.grad += -out.grad

        out._backward = _backward
        return out

    def __sub__(self, other):
        return self + (-_as_tensor(other))

    def __rsub__(self, other):
        return _as_tensor(other) + (-self)

    def __mul__(self, other):
        other = _as_tensor(other)
        out = self._make_out(self.data * other.data, (self, other), "*", None)

        def _backward():
            if self.requires_grad:
                self.grad += _unbroadcast(out.grad * other.data, self.data.shape)
            if other.requires_grad:
                other.grad += _unbroadcast(out.grad * self.data, other.data.shape)

        out._backward = _backward
        return out

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = _as_tensor(other)
        return self * other.pow(-1.0)

    def __rtruediv__(self, other):
        return _as_tensor(other) * self.pow(-1.0)

    def pow(self, p):
        out = self._make_out(self.data ** p, (self,), f"**{p}", None)

        def _backward():
            if self.requires_grad:
                self.grad += (p * self.data ** (p - 1)) * out.grad

        out._backward = _backward
        return out

    def __pow__(self, p):
        return self.pow(p)

    # ---- matmul ---------------------------------------------------------
    def matmul(self, other):
        other = _as_tensor(other)
        out = self._make_out(self.data @ other.data, (self, other), "@", None)

        def _backward():
            if self.requires_grad:
                g = out.grad @ np.swapaxes(other.data, -1, -2)
                self.grad += _unbroadcast(g, self.data.shape)
            if other.requires_grad:
                g = np.swapaxes(self.data, -1, -2) @ out.grad
                other.grad += _unbroadcast(g, other.data.shape)

        out._backward = _backward
        return out

    def __matmul__(self, other):
        return self.matmul(other)

    # ---- shape ops --------------------------------------------------------
    def reshape(self, *shape):
        if len(shape) == 1 and isinstance(shape[0], (tuple, list)):
            shape = tuple(shape[0])
        orig_shape = self.data.shape
        out = self._make_out(self.data.reshape(*shape), (self,), "reshape", None)

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
        out = self._make_out(np.transpose(self.data, axes), (self,), "transpose", None)

        def _backward():
            if self.requires_grad:
                self.grad += np.transpose(out.grad, inv)

        out._backward = _backward
        return out

    @property
    def T(self):
        return self.transpose()

    def swapaxes(self, a, b):
        ndim = self.data.ndim
        axes = list(range(ndim))
        axes[a], axes[b] = axes[b], axes[a]
        return self.transpose(*axes)

    # ---- reductions ---------------------------------------------------
    def sum(self, axis=None, keepdims=False):
        out_data = self.data.sum(axis=axis, keepdims=keepdims)
        in_shape = self.data.shape
        out = self._make_out(out_data, (self,), "sum", None)

        def _backward():
            if self.requires_grad:
                g = out.grad
                if not keepdims and axis is not None:
                    ax = (axis,) if isinstance(axis, int) else tuple(axis)
                    for a in sorted(ax):
                        g = np.expand_dims(g, a)
                self.grad += np.broadcast_to(g, in_shape).copy()

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

    # ---- elementwise nonlinearities ------------------------------------
    def exp(self):
        e = np.exp(self.data)
        out = self._make_out(e, (self,), "exp", None)

        def _backward():
            if self.requires_grad:
                self.grad += e * out.grad

        out._backward = _backward
        return out

    def log(self):
        out = self._make_out(np.log(self.data), (self,), "log", None)

        def _backward():
            if self.requires_grad:
                self.grad += out.grad / self.data

        out._backward = _backward
        return out

    def sqrt(self):
        return self.pow(0.5)

    def tanh(self):
        t = np.tanh(self.data)
        out = self._make_out(t, (self,), "tanh", None)

        def _backward():
            if self.requires_grad:
                self.grad += (1.0 - t * t) * out.grad

        out._backward = _backward
        return out

    def relu(self):
        mask = (self.data > 0).astype(np.float64)
        out = self._make_out(self.data * mask, (self,), "relu", None)

        def _backward():
            if self.requires_grad:
                self.grad += out.grad * mask

        out._backward = _backward
        return out

    # ---- softmax (primitive, numerically stable) ----------------------
    def softmax(self, axis=-1):
        x = self.data
        m = np.max(x, axis=axis, keepdims=True)
        e = np.exp(x - m)
        s = e / np.sum(e, axis=axis, keepdims=True)
        out = self._make_out(s, (self,), "softmax", None)

        def _backward():
            if self.requires_grad:
                dot = np.sum(out.grad * s, axis=axis, keepdims=True)
                self.grad += s * (out.grad - dot)

        out._backward = _backward
        return out

    # ---- embedding lookup (differentiable weight, integer indices) ----
    def embedding(self, indices):
        """self: weight Tensor of shape (vocab, dim). indices: int array of
        any shape. Returns Tensor of shape indices.shape + (dim,)."""
        idx = np.asarray(indices)
        out_data = self.data[idx]
        out = self._make_out(out_data, (self,), "embedding", None)

        def _backward():
            if self.requires_grad:
                np.add.at(self.grad, idx, out.grad)

        out._backward = _backward
        return out

    # ---- cross entropy (primitive; combines log-softmax + NLL) --------
    def cross_entropy(self, targets):
        """self: logits Tensor of shape (N, C). targets: int array (N,).
        Returns scalar Tensor = mean NLL loss."""
        logits = self.data
        targets = np.asarray(targets)
        n = logits.shape[0]
        m = np.max(logits, axis=-1, keepdims=True)
        shifted = logits - m
        logsumexp = np.log(np.sum(np.exp(shifted), axis=-1, keepdims=True)) + m
        log_probs = logits - logsumexp
        nll = -log_probs[np.arange(n), targets]
        loss_val = nll.mean()

        probs = np.exp(log_probs)
        out = self._make_out(loss_val, (self,), "cross_entropy", None)

        def _backward():
            if self.requires_grad:
                grad = probs.copy()
                grad[np.arange(n), targets] -= 1.0
                grad /= n
                self.grad += grad * out.grad

        out._backward = _backward
        return out

    # ---- indexing (read-only slice, e.g. positional embedding lookup) -
    def __getitem__(self, key):
        out_data = self.data[key]
        in_shape = self.data.shape
        out = self._make_out(out_data, (self,), "getitem", None)

        def _backward():
            if self.requires_grad:
                g = np.zeros(in_shape, dtype=np.float64)
                np.add.at(g, key, out.grad)
                self.grad += g

        out._backward = _backward
        return out

    # ---- backward pass --------------------------------------------------
    def backward(self, grad=None):
        assert self.requires_grad, "called backward() on a tensor with requires_grad=False"
        if grad is None:
            assert self.data.shape == (), "grad must be specified for non-scalar outputs"
            grad = np.ones_like(self.data)
        else:
            grad = np.asarray(grad, dtype=np.float64)

        topo, visited = [], set()

        def build(v):
            if id(v) not in visited:
                visited.add(id(v))
                for child in v._prev:
                    build(child)
                topo.append(v)

        build(self)

        for v in topo:
            if v.requires_grad and v.grad is None:
                v.grad = np.zeros_like(v.data)

        self.grad = grad
        for v in reversed(topo):
            if v.requires_grad:
                v._backward()

        # Every op's backward closure captures its own `out` (to read
        # out.grad), which makes out._backward -> closure -> out a reference
        # cycle. Refcounting alone can't free those, so a training loop that
        # builds a fresh graph every step relies on the generational cyclic
        # GC to keep up -- in practice it lags behind allocation and memory
        # balloons. Since a graph is single-use (no retain_graph support
        # here), explicitly drop the closures and parent links right after
        # backward() so refcounting reclaims the graph immediately. Only
        # touch nodes that actually HAVE children: leaf/parameter tensors
        # (empty _prev) persist across training steps and must keep their
        # harmless default no-op _backward intact for reuse in later graphs.
        for v in topo:
            if v._prev:
                v._backward = None
                v._prev = ()

    def item(self):
        return float(self.data)

    def __repr__(self):
        return f"Tensor(shape={self.data.shape}, requires_grad={self.requires_grad})"


def concatenate(tensors, axis=-1):
    """Concatenate a list of Tensors along `axis`."""
    datas = [t.data for t in tensors]
    out_data = np.concatenate(datas, axis=axis)
    req = _GRAD_ENABLED and any(t.requires_grad for t in tensors)
    out = Tensor(out_data, requires_grad=req, _children=tuple(tensors) if req else (), _op="concat")
    sizes = [d.shape[axis] for d in datas]

    def _backward():
        splits = np.split(out.grad, np.cumsum(sizes)[:-1], axis=axis)
        for t, g in zip(tensors, splits):
            if t.requires_grad:
                t.grad += g

    if req:
        out._backward = _backward
    return out
