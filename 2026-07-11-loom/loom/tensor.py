"""A reverse-mode autodiff engine over numpy arrays.

This is the load-bearing piece of Loom: every operator below owns both a
forward numpy computation and a hand-derived backward closure that
accumulates gradients into its inputs. Nothing here calls into
PyTorch/JAX/autograd — `numpy` is used strictly as a fast ndarray container
and BLAS matmul. Every op is verified against finite-difference gradients in
`gradcheck.py` / `tests/test_tensor.py`.

Broadcasting note: numpy silently broadcasts shapes in elementwise ops and in
batched matmul. When a gradient flows back into an input that was
broadcast up to a larger shape, it must be summed back down ("unbroadcast")
to the input's original shape before accumulating -- this is the single most
common source of tensor-autodiff bugs, so `_unbroadcast` is centralized and
gradient-checked directly.
"""
import numpy as np

_EPS = 1e-5


def _unbroadcast(grad, shape):
    """Sum-reduce `grad` (numpy array) down to `shape`, undoing any numpy
    broadcasting that happened during the forward op."""
    if grad.shape == shape:
        return grad
    # Drop extra leading dims introduced by broadcasting.
    ndims_added = grad.ndim - len(shape)
    for _ in range(ndims_added):
        grad = grad.sum(axis=0)
    # Sum over dims that were size-1 in the original shape but got broadcast.
    for i, dim in enumerate(shape):
        if dim == 1 and grad.shape[i] != 1:
            grad = grad.sum(axis=i, keepdims=True)
    return grad.reshape(shape)


class Tensor:
    __slots__ = ("data", "grad", "requires_grad", "_prev", "_backward", "_op")

    def __init__(self, data, requires_grad=False, _prev=(), _op=""):
        self.data = np.asarray(data, dtype=np.float64)
        self.grad = None
        self.requires_grad = requires_grad
        self._prev = _prev
        self._backward = lambda: None
        self._op = _op

    # -- bookkeeping ---------------------------------------------------
    @property
    def shape(self):
        return self.data.shape

    @property
    def ndim(self):
        return self.data.ndim

    def __repr__(self):
        return f"Tensor(shape={self.shape}, op={self._op!r}, requires_grad={self.requires_grad})"

    def zero_grad(self):
        self.grad = None

    def _ensure_grad(self):
        if self.grad is None:
            self.grad = np.zeros_like(self.data)

    def _accum(self, g):
        if self.requires_grad:
            self._ensure_grad()
            self.grad = self.grad + g

    def backward(self, grad=None):
        if grad is None:
            if self.data.shape != ():
                raise ValueError("backward() with no grad argument requires a scalar tensor")
            grad = np.ones_like(self.data)
        else:
            grad = np.asarray(grad, dtype=np.float64)

        topo = []
        visited = set()

        def build(node):
            if id(node) not in visited:
                visited.add(id(node))
                for child in node._prev:
                    build(child)
                topo.append(node)

        build(self)

        self._ensure_grad()
        self.grad = grad
        for node in reversed(topo):
            node._backward()

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _wrap(x):
        return x if isinstance(x, Tensor) else Tensor(x)

    # -- elementwise arithmetic ------------------------------------------
    def __add__(self, other):
        other = Tensor._wrap(other)
        out = Tensor(self.data + other.data, requires_grad=(self.requires_grad or other.requires_grad),
                     _prev=(self, other), _op="+")

        def _backward():
            if out.grad is None:
                return
            self._accum(_unbroadcast(out.grad, self.data.shape))
            other._accum(_unbroadcast(out.grad, other.data.shape))

        out._backward = _backward
        return out

    __radd__ = __add__

    def __neg__(self):
        out = Tensor(-self.data, requires_grad=self.requires_grad, _prev=(self,), _op="neg")

        def _backward():
            if out.grad is None:
                return
            self._accum(-out.grad)

        out._backward = _backward
        return out

    def __sub__(self, other):
        return self + (-Tensor._wrap(other))

    def __rsub__(self, other):
        return Tensor._wrap(other) + (-self)

    def __mul__(self, other):
        other = Tensor._wrap(other)
        out = Tensor(self.data * other.data, requires_grad=(self.requires_grad or other.requires_grad),
                     _prev=(self, other), _op="*")

        def _backward():
            if out.grad is None:
                return
            self._accum(_unbroadcast(out.grad * other.data, self.data.shape))
            other._accum(_unbroadcast(out.grad * self.data, other.data.shape))

        out._backward = _backward
        return out

    __rmul__ = __mul__

    def __truediv__(self, other):
        other = Tensor._wrap(other)
        return self * (other ** -1.0)

    def __rtruediv__(self, other):
        return Tensor._wrap(other) * (self ** -1.0)

    def __pow__(self, p):
        assert isinstance(p, (int, float)), "only scalar exponents are supported"
        out = Tensor(self.data ** p, requires_grad=self.requires_grad, _prev=(self,), _op=f"**{p}")

        def _backward():
            if out.grad is None:
                return
            self._accum(out.grad * (p * self.data ** (p - 1)))

        out._backward = _backward
        return out

    # -- matmul (with batching / broadcasting over leading dims) --------
    def __matmul__(self, other):
        other = Tensor._wrap(other)
        out = Tensor(self.data @ other.data, requires_grad=(self.requires_grad or other.requires_grad),
                     _prev=(self, other), _op="matmul")

        def _backward():
            if out.grad is None:
                return
            g = out.grad
            a, b = self.data, other.data
            if a.ndim == 1 and b.ndim == 1:
                self._accum(_unbroadcast(g * b, a.shape))
                other._accum(_unbroadcast(g * a, b.shape))
                return
            b_t = np.swapaxes(b, -1, -2) if b.ndim >= 2 else b
            a_t = np.swapaxes(a, -1, -2) if a.ndim >= 2 else a
            da = g @ b_t if b.ndim >= 2 else np.expand_dims(g, -1) * b
            db = a_t @ g if a.ndim >= 2 else np.expand_dims(a, -1) * g
            self._accum(_unbroadcast(da, a.shape))
            other._accum(_unbroadcast(db, b.shape))

        out._backward = _backward
        return out

    # -- shape ops --------------------------------------------------------
    def reshape(self, *shape):
        if len(shape) == 1 and isinstance(shape[0], (tuple, list)):
            shape = tuple(shape[0])
        orig_shape = self.data.shape
        out = Tensor(self.data.reshape(shape), requires_grad=self.requires_grad, _prev=(self,), _op="reshape")

        def _backward():
            if out.grad is None:
                return
            self._accum(out.grad.reshape(orig_shape))

        out._backward = _backward
        return out

    def transpose(self, *axes):
        if len(axes) == 1 and isinstance(axes[0], (tuple, list)):
            axes = tuple(axes[0])
        if not axes:
            axes = tuple(reversed(range(self.data.ndim)))
        out = Tensor(self.data.transpose(axes), requires_grad=self.requires_grad, _prev=(self,), _op="transpose")
        inv = np.argsort(axes)

        def _backward():
            if out.grad is None:
                return
            self._accum(out.grad.transpose(inv))

        out._backward = _backward
        return out

    def swapaxes(self, a, b):
        ndim = self.data.ndim
        axes = list(range(ndim))
        axes[a], axes[b] = axes[b], axes[a]
        return self.transpose(*axes)

    def __getitem__(self, idx):
        out = Tensor(self.data[idx], requires_grad=self.requires_grad, _prev=(self,), _op="getitem")

        def _backward():
            if out.grad is None:
                return
            self._ensure_grad()
            np.add.at(self.grad, idx, out.grad)

        out._backward = _backward
        return out

    # -- reductions ---------------------------------------------------------
    def sum(self, axis=None, keepdims=False):
        out = Tensor(self.data.sum(axis=axis, keepdims=keepdims), requires_grad=self.requires_grad,
                     _prev=(self,), _op="sum")

        def _backward():
            if out.grad is None:
                return
            g = out.grad
            if not keepdims and axis is not None:
                ax = (axis,) if isinstance(axis, int) else tuple(axis)
                for a in sorted(a % self.data.ndim for a in ax):
                    g = np.expand_dims(g, a)
            self._accum(np.broadcast_to(g, self.data.shape).copy())

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

    # -- elementwise nonlinearities -------------------------------------
    def exp(self):
        e = np.exp(self.data)
        out = Tensor(e, requires_grad=self.requires_grad, _prev=(self,), _op="exp")

        def _backward():
            if out.grad is None:
                return
            self._accum(out.grad * e)

        out._backward = _backward
        return out

    def log(self):
        out = Tensor(np.log(self.data), requires_grad=self.requires_grad, _prev=(self,), _op="log")

        def _backward():
            if out.grad is None:
                return
            self._accum(out.grad / self.data)

        out._backward = _backward
        return out

    def tanh(self):
        t = np.tanh(self.data)
        out = Tensor(t, requires_grad=self.requires_grad, _prev=(self,), _op="tanh")

        def _backward():
            if out.grad is None:
                return
            self._accum(out.grad * (1 - t * t))

        out._backward = _backward
        return out

    def relu(self):
        mask = self.data > 0
        out = Tensor(self.data * mask, requires_grad=self.requires_grad, _prev=(self,), _op="relu")

        def _backward():
            if out.grad is None:
                return
            self._accum(out.grad * mask)

        out._backward = _backward
        return out

    def gelu(self):
        """GPT-2's tanh approximation of GELU, with an exact analytic gradient
        (not composed from other ops, for numerical efficiency; verified by
        finite-difference gradcheck like every other op)."""
        x = self.data
        c = np.sqrt(2.0 / np.pi)
        inner = c * (x + 0.044715 * x ** 3)
        t = np.tanh(inner)
        cdf = 0.5 * (1.0 + t)
        y = x * cdf
        out = Tensor(y, requires_grad=self.requires_grad, _prev=(self,), _op="gelu")

        def _backward():
            if out.grad is None:
                return
            sech2 = 1 - t * t
            dinner_dx = c * (1 + 3 * 0.044715 * x ** 2)
            dy_dx = cdf + x * 0.5 * sech2 * dinner_dx
            self._accum(out.grad * dy_dx)

        out._backward = _backward
        return out

    def softmax(self, axis=-1):
        x = self.data
        shifted = x - np.max(x, axis=axis, keepdims=True)
        e = np.exp(shifted)
        s = e / np.sum(e, axis=axis, keepdims=True)
        out = Tensor(s, requires_grad=self.requires_grad, _prev=(self,), _op="softmax")

        def _backward():
            if out.grad is None:
                return
            g = out.grad
            dot = np.sum(g * s, axis=axis, keepdims=True)
            self._accum(s * (g - dot))

        out._backward = _backward
        return out

    def masked_fill(self, mask, value):
        """`mask` is a plain numpy bool array (broadcastable to self.shape);
        positions where mask is True are set to `value`. Gradient passes
        through unmasked positions only -- filled positions get zero grad
        since `value` is a constant, not a differentiable input."""
        bmask = np.broadcast_to(mask, self.data.shape)
        out = Tensor(np.where(bmask, value, self.data), requires_grad=self.requires_grad,
                     _prev=(self,), _op="masked_fill")

        def _backward():
            if out.grad is None:
                return
            self._accum(np.where(bmask, 0.0, out.grad))

        out._backward = _backward
        return out

    def layernorm(self, gamma, beta, eps=1e-5):
        """LayerNorm over the last axis. `gamma`/`beta` are Tensors of shape
        (dim,). Hand-derived backward (the standard LN backward formula)."""
        x = self.data
        mu = x.mean(axis=-1, keepdims=True)
        xc = x - mu
        var = (xc ** 2).mean(axis=-1, keepdims=True)
        std_inv = 1.0 / np.sqrt(var + eps)
        xhat = xc * std_inv
        g, b = gamma.data, beta.data
        y = xhat * g + b
        requires = self.requires_grad or gamma.requires_grad or beta.requires_grad
        out = Tensor(y, requires_grad=requires, _prev=(self, gamma, beta), _op="layernorm")
        N = x.shape[-1]

        def _backward():
            if out.grad is None:
                return
            dy = out.grad
            gamma._accum(_unbroadcast((dy * xhat).reshape(-1, N).sum(axis=0), g.shape))
            beta._accum(_unbroadcast(dy.reshape(-1, N).sum(axis=0), b.shape))
            dxhat = dy * g
            dvar_term = np.sum(dxhat * xc, axis=-1, keepdims=True) * (-0.5) * std_inv ** 3
            dmu_term = -np.sum(dxhat * std_inv, axis=-1, keepdims=True) - dvar_term * 2.0 * np.mean(xc, axis=-1, keepdims=True)
            dx = dxhat * std_inv + dvar_term * 2.0 * xc / N + dmu_term / N
            self._accum(dx)

        out._backward = _backward
        return out

    def cross_entropy(self, targets):
        """self: logits of shape (..., V). targets: int array of shape (...)
        with class indices. Returns a scalar mean negative log-likelihood
        loss Tensor, computed via a numerically-stable fused log-softmax +
        gather so the backward pass is the clean `softmax(logits) - one_hot`
        rather than composing softmax+log+gather (which is also correct but
        slower and more failure-prone to derive by hand)."""
        x = self.data
        targets = np.asarray(targets)
        flat_x = x.reshape(-1, x.shape[-1])
        flat_t = targets.reshape(-1)
        shifted = flat_x - flat_x.max(axis=-1, keepdims=True)
        logsumexp = np.log(np.sum(np.exp(shifted), axis=-1, keepdims=True))
        log_probs = shifted - logsumexp
        n = flat_t.shape[0]
        picked = log_probs[np.arange(n), flat_t]
        loss_val = -picked.mean()
        out = Tensor(loss_val, requires_grad=self.requires_grad, _prev=(self,), _op="cross_entropy")

        def _backward():
            if out.grad is None:
                return
            probs = np.exp(log_probs)
            grad = probs.copy()
            grad[np.arange(n), flat_t] -= 1.0
            grad *= (out.grad / n)
            self._accum(grad.reshape(x.shape))

        out._backward = _backward
        return out


def embedding(weight, idx):
    """weight: Tensor of shape (num_embeddings, dim). idx: int numpy array of
    any shape. Returns a Tensor of shape idx.shape + (dim,). Backward
    scatter-adds into weight.grad at the looked-up rows (rows can repeat
    within a batch, hence `np.add.at` rather than plain indexed assignment)."""
    idx = np.asarray(idx)
    out_data = weight.data[idx]
    out = Tensor(out_data, requires_grad=weight.requires_grad, _prev=(weight,), _op="embedding")

    def _backward():
        if out.grad is None:
            return
        weight._ensure_grad()
        np.add.at(weight.grad, idx, out.grad)

    out._backward = _backward
    return out
