"""A from-scratch reverse-mode autodiff engine over numpy arrays.

No PyTorch/TensorFlow/JAX/autograd. Every operator below builds its own
node in a computation graph and defines its own local backward rule; the
`Tensor.backward()` method does a plain topological sort and calls each
node's local rule in reverse order, accumulating gradients. This is the
same design as a scalar autodiff engine (micrograd-style DAG), just with
numpy arrays as the payload and broadcasting-aware backward rules.
"""
import numpy as np

_EPS = 1e-8


def _unbroadcast(grad, shape):
    """Sum-reduce `grad` down to `shape`, undoing numpy broadcasting."""
    while grad.ndim > len(shape):
        grad = grad.sum(axis=0)
    for axis, dim in enumerate(shape):
        if dim == 1 and grad.shape[axis] != 1:
            grad = grad.sum(axis=axis, keepdims=True)
    return grad.reshape(shape)


class Tensor:
    __slots__ = ("data", "grad", "requires_grad", "_backward", "_prev", "_op")

    def __init__(self, data, requires_grad=False, _prev=(), _op=""):
        self.data = np.asarray(data, dtype=np.float64)
        self.requires_grad = requires_grad
        self.grad = None
        self._backward = lambda: None
        self._prev = _prev
        self._op = _op

    @property
    def shape(self):
        return self.data.shape

    def __repr__(self):
        return f"Tensor(shape={self.data.shape}, op={self._op!r})"

    # ---- graph plumbing ----------------------------------------------

    def _make(self, data, prev, op):
        req = any(p.requires_grad for p in prev)
        return Tensor(data, requires_grad=req, _prev=prev, _op=op)

    def backward(self, grad=None):
        if grad is None:
            if self.data.shape != ():
                raise ValueError("backward() with no grad only valid for scalars")
            grad = np.ones_like(self.data)
        else:
            grad = np.asarray(grad, dtype=np.float64)

        topo = []
        visited = set()

        def build(v):
            if id(v) not in visited:
                visited.add(id(v))
                for p in v._prev:
                    build(p)
                topo.append(v)

        build(self)

        self.grad = grad if self.grad is None else self.grad + grad
        for v in reversed(topo):
            if v.requires_grad:
                v._backward()

    def _accum(self, g):
        if not self.requires_grad:
            return
        self.grad = g if self.grad is None else self.grad + g

    # ---- basic arithmetic ----------------------------------------------

    def __add__(self, other):
        other = other if isinstance(other, Tensor) else Tensor(other)
        out = self._make(self.data + other.data, (self, other), "add")

        def _backward():
            self._accum(_unbroadcast(out.grad, self.data.shape))
            other._accum(_unbroadcast(out.grad, other.data.shape))
        out._backward = _backward
        return out

    __radd__ = __add__

    def __neg__(self):
        out = self._make(-self.data, (self,), "neg")

        def _backward():
            self._accum(-out.grad)
        out._backward = _backward
        return out

    def __sub__(self, other):
        other = other if isinstance(other, Tensor) else Tensor(other)
        return self + (-other)

    def __rsub__(self, other):
        other = other if isinstance(other, Tensor) else Tensor(other)
        return other + (-self)

    def __mul__(self, other):
        other = other if isinstance(other, Tensor) else Tensor(other)
        out = self._make(self.data * other.data, (self, other), "mul")

        def _backward():
            self._accum(_unbroadcast(out.grad * other.data, self.data.shape))
            other._accum(_unbroadcast(out.grad * self.data, other.data.shape))
        out._backward = _backward
        return out

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = other if isinstance(other, Tensor) else Tensor(other)
        return self * other._pow_const(-1.0)

    def _pow_const(self, p):
        out = self._make(self.data ** p, (self,), f"pow{p}")

        def _backward():
            self._accum(_unbroadcast(out.grad * p * self.data ** (p - 1), self.data.shape))
        out._backward = _backward
        return out

    def __pow__(self, p):
        assert isinstance(p, (int, float))
        return self._pow_const(p)

    def matmul(self, other):
        assert isinstance(other, Tensor)
        out = self._make(self.data @ other.data, (self, other), "matmul")

        def _backward():
            a, b = self.data, other.data
            ga = out.grad @ np.swapaxes(b, -1, -2)
            gb = np.swapaxes(a, -1, -2) @ out.grad
            self._accum(_unbroadcast(ga, a.shape))
            other._accum(_unbroadcast(gb, b.shape))
        out._backward = _backward
        return out

    def __matmul__(self, other):
        return self.matmul(other)

    # ---- shape ops ------------------------------------------------------

    def reshape(self, *shape):
        if len(shape) == 1 and isinstance(shape[0], (tuple, list)):
            shape = tuple(shape[0])
        orig_shape = self.data.shape
        out = self._make(self.data.reshape(shape), (self,), "reshape")

        def _backward():
            self._accum(out.grad.reshape(orig_shape))
        out._backward = _backward
        return out

    def permute(self, *axes):
        if len(axes) == 1 and isinstance(axes[0], (tuple, list)):
            axes = tuple(axes[0])
        out = self._make(np.transpose(self.data, axes), (self,), "permute")
        inv = np.argsort(axes)

        def _backward():
            self._accum(np.transpose(out.grad, inv))
        out._backward = _backward
        return out

    def transpose_last2(self):
        n = self.data.ndim
        axes = list(range(n))
        axes[-1], axes[-2] = axes[-2], axes[-1]
        return self.permute(*axes)

    def __getitem__(self, key):
        if isinstance(key, np.ndarray) or (isinstance(key, list)):
            idx = np.asarray(key)
            out = self._make(self.data[idx], (self,), "gather0")

            def _backward():
                g = np.zeros_like(self.data)
                np.add.at(g, idx, out.grad)
                self._accum(g)
            out._backward = _backward
            return out
        out = self._make(self.data[key], (self,), "slice")

        def _backward():
            g = np.zeros_like(self.data)
            g[key] = out.grad
            self._accum(g)
        out._backward = _backward
        return out

    def concat(tensors, axis=-1):
        arrs = [t.data for t in tensors]
        out_data = np.concatenate(arrs, axis=axis)
        out = tensors[0]._make(out_data, tuple(tensors), "concat")
        sizes = [a.shape[axis] for a in arrs]

        def _backward():
            splits = np.split(out.grad, np.cumsum(sizes)[:-1], axis=axis)
            for t, g in zip(tensors, splits):
                t._accum(g)
        out._backward = _backward
        return out
    concat = staticmethod(concat)

    # ---- reductions -------------------------------------------------------

    def sum(self, axis=None, keepdims=False):
        out = self._make(self.data.sum(axis=axis, keepdims=keepdims), (self,), "sum")
        in_shape = self.data.shape

        def _backward():
            g = out.grad
            if not keepdims and axis is not None:
                ax = axis if isinstance(axis, tuple) else (axis,)
                g = np.expand_dims(g, ax)
            self._accum(np.broadcast_to(g, in_shape).copy())
        out._backward = _backward
        return out

    def mean(self, axis=None, keepdims=False):
        if axis is None:
            n = self.data.size
        else:
            ax = axis if isinstance(axis, tuple) else (axis,)
            n = 1
            for a in ax:
                n *= self.data.shape[a]
        return self.sum(axis=axis, keepdims=keepdims) * (1.0 / n)

    # ---- elementwise nonlinearities ----------------------------------------

    def exp(self):
        out = self._make(np.exp(self.data), (self,), "exp")

        def _backward():
            self._accum(out.grad * out.data)
        out._backward = _backward
        return out

    def log(self):
        out = self._make(np.log(self.data + _EPS), (self,), "log")

        def _backward():
            self._accum(out.grad / (self.data + _EPS))
        out._backward = _backward
        return out

    def tanh(self):
        t = np.tanh(self.data)
        out = self._make(t, (self,), "tanh")

        def _backward():
            self._accum(out.grad * (1 - t * t))
        out._backward = _backward
        return out

    def relu(self):
        out = self._make(np.maximum(self.data, 0), (self,), "relu")

        def _backward():
            self._accum(out.grad * (self.data > 0))
        out._backward = _backward
        return out

    def gelu(self):
        """tanh-approximation GELU, composed from primitive ops so its
        gradient is produced by the engine itself, not hand-derived."""
        c = 0.7978845608028654  # sqrt(2/pi)
        x3 = self * self * self
        inner = (self + x3 * 0.044715) * c
        return self * (inner.tanh() + 1.0) * 0.5

    def softmax(self, axis=-1):
        m = np.max(self.data, axis=axis, keepdims=True)
        e = np.exp(self.data - m)
        s = e / e.sum(axis=axis, keepdims=True)
        out = self._make(s, (self,), "softmax")

        def _backward():
            g = out.grad
            dot = np.sum(g * s, axis=axis, keepdims=True)
            self._accum(s * (g - dot))
        out._backward = _backward
        return out

    def layernorm(self, gamma, beta, eps=1e-5):
        """LayerNorm over the last axis. gamma/beta are Tensors of shape (D,)."""
        x = self.data
        D = x.shape[-1]
        mu = x.mean(axis=-1, keepdims=True)
        xc = x - mu
        var = (xc * xc).mean(axis=-1, keepdims=True)
        std = np.sqrt(var + eps)
        xhat = xc / std
        y = xhat * gamma.data + beta.data
        out = self._make(y, (self, gamma, beta), "layernorm")

        def _backward():
            dy = out.grad
            gamma._accum(_unbroadcast(np.sum(dy * xhat, axis=tuple(range(dy.ndim - 1))), gamma.data.shape))
            beta._accum(_unbroadcast(np.sum(dy, axis=tuple(range(dy.ndim - 1))), beta.data.shape))
            dxhat = dy * gamma.data
            dx = (1.0 / D) / std * (
                D * dxhat
                - np.sum(dxhat, axis=-1, keepdims=True)
                - xhat * np.sum(dxhat * xhat, axis=-1, keepdims=True)
            )
            self._accum(dx)
        out._backward = _backward
        return out

    # ---- misc ----------------------------------------------------------

    def item(self):
        return float(self.data)
