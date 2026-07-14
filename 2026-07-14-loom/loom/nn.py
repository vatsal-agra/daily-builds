"""Hand-rolled neural network primitives: every forward() has a matching
backward() computing the exact analytic gradient by hand (matrix calculus),
not via any autodiff library. Correctness is proven in gradcheck.py by
comparing each backward() against a numerical finite-difference gradient.
"""
import math

import numpy as np


class Parameter:
    """A learnable array plus its accumulated gradient."""

    def __init__(self, value):
        self.value = np.asarray(value, dtype=np.float64)
        self.grad = np.zeros_like(self.value)

    def zero_grad(self):
        self.grad[...] = 0.0


def _he_init(rng, shape, fan_in):
    return rng.randn(*shape) / math.sqrt(fan_in)


class Linear:
    def __init__(self, in_dim, out_dim, bias=True, rng=None):
        rng = rng or np.random
        self.W = Parameter(_he_init(rng, (in_dim, out_dim), in_dim))
        self.b = Parameter(np.zeros(out_dim)) if bias else None
        self._x = None

    def forward(self, x):
        self._x = x
        y = x @ self.W.value
        if self.b is not None:
            y = y + self.b.value
        return y

    def backward(self, dy):
        x = self._x
        x2 = x.reshape(-1, x.shape[-1])
        dy2 = dy.reshape(-1, dy.shape[-1])
        self.W.grad += x2.T @ dy2
        if self.b is not None:
            self.b.grad += dy2.sum(axis=0)
        dx = dy @ self.W.value.T
        return dx

    def parameters(self):
        return [self.W] + ([self.b] if self.b is not None else [])


class LayerNorm:
    def __init__(self, dim, eps=1e-5):
        self.gamma = Parameter(np.ones(dim))
        self.beta = Parameter(np.zeros(dim))
        self.eps = eps
        self._cache = None

    def forward(self, x):
        mu = x.mean(axis=-1, keepdims=True)
        var = x.var(axis=-1, keepdims=True)
        std = np.sqrt(var + self.eps)
        xhat = (x - mu) / std
        self._cache = (xhat, std)
        return xhat * self.gamma.value + self.beta.value

    def backward(self, dy):
        xhat, std = self._cache
        D = xhat.shape[-1]
        self.gamma.grad += (dy * xhat).reshape(-1, D).sum(axis=0)
        self.beta.grad += dy.reshape(-1, D).sum(axis=0)

        dxhat = dy * self.gamma.value
        mean_dxhat = dxhat.mean(axis=-1, keepdims=True)
        mean_dxhat_xhat = (dxhat * xhat).mean(axis=-1, keepdims=True)
        dx = (dxhat - mean_dxhat - xhat * mean_dxhat_xhat) / std
        return dx

    def parameters(self):
        return [self.gamma, self.beta]


class Embedding:
    def __init__(self, vocab_size, dim, rng=None):
        rng = rng or np.random
        self.W = Parameter(rng.randn(vocab_size, dim) * 0.02)
        self._ids = None

    def forward(self, ids):
        self._ids = ids
        return self.W.value[ids]

    def backward(self, dy):
        np.add.at(self.W.grad, self._ids, dy)

    def parameters(self):
        return [self.W]


class GELU:
    """Tanh-approximate GELU (the GPT-2 formulation), with an exact analytic
    derivative — not a numerically-approximated one."""

    _C = math.sqrt(2.0 / math.pi)

    def __init__(self):
        self._cache = None

    def forward(self, x):
        u = self._C * (x + 0.044715 * x ** 3)
        t = np.tanh(u)
        self._cache = (x, t)
        return 0.5 * x * (1.0 + t)

    def backward(self, dy):
        x, t = self._cache
        du_dx = self._C * (1.0 + 3 * 0.044715 * x ** 2)
        dgelu_dx = 0.5 * (1.0 + t) + 0.5 * x * (1.0 - t ** 2) * du_dx
        return dy * dgelu_dx


def softmax(x, axis=-1):
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


class FeedForward:
    def __init__(self, d_model, expansion=4, rng=None):
        self.fc1 = Linear(d_model, expansion * d_model, rng=rng)
        self.act = GELU()
        self.fc2 = Linear(expansion * d_model, d_model, rng=rng)

    def forward(self, x):
        h = self.fc1.forward(x)
        h = self.act.forward(h)
        return self.fc2.forward(h)

    def backward(self, dy):
        dh = self.fc2.backward(dy)
        dh = self.act.backward(dh)
        return self.fc1.backward(dh)

    def parameters(self):
        return self.fc1.parameters() + self.fc2.parameters()


class CausalSelfAttention:
    """Multi-head causal (autoregressive) self-attention, backprop by hand."""

    def __init__(self, d_model, n_heads, rng=None):
        if d_model % n_heads != 0:
            raise ValueError("d_model must be divisible by n_heads")
        self.n_heads = n_heads
        self.d_head = d_model // n_heads
        self.q_proj = Linear(d_model, d_model, rng=rng)
        self.k_proj = Linear(d_model, d_model, rng=rng)
        self.v_proj = Linear(d_model, d_model, rng=rng)
        self.out_proj = Linear(d_model, d_model, rng=rng)
        self._cache = None
        self._mask_cache = {}

    def _causal_mask(self, T):
        mask = self._mask_cache.get(T)
        if mask is None:
            mask = np.triu(np.full((T, T), -np.inf), k=1)
            self._mask_cache[T] = mask
        return mask

    def forward(self, x):
        B, T, D = x.shape
        H, Dh = self.n_heads, self.d_head

        def split_heads(t):
            return t.reshape(B, T, H, Dh).transpose(0, 2, 1, 3)

        q = split_heads(self.q_proj.forward(x))
        k = split_heads(self.k_proj.forward(x))
        v = split_heads(self.v_proj.forward(x))

        scores = (q @ k.transpose(0, 1, 3, 2)) / math.sqrt(Dh)
        scores = scores + self._causal_mask(T)
        probs = softmax(scores, axis=-1)
        out = probs @ v  # (B,H,T,Dh)

        merged = out.transpose(0, 2, 1, 3).reshape(B, T, D)
        y = self.out_proj.forward(merged)
        self._cache = (B, T, H, Dh, q, k, v, probs)
        return y, probs

    def backward(self, dy):
        B, T, H, Dh, q, k, v, probs = self._cache
        dmerged = self.out_proj.backward(dy)
        dout = dmerged.reshape(B, T, H, Dh).transpose(0, 2, 1, 3)  # (B,H,T,Dh)

        dprobs = dout @ v.transpose(0, 1, 3, 2)  # (B,H,T,T)
        dv = probs.transpose(0, 1, 3, 2) @ dout  # (B,H,T,Dh)

        # softmax backward: dscores_ij = probs_ij * (dprobs_ij - sum_l probs_il*dprobs_il)
        dscores = probs * (dprobs - (dprobs * probs).sum(axis=-1, keepdims=True))
        dscores = dscores / math.sqrt(Dh)

        dq = dscores @ k  # (B,H,T,Dh)
        dk = dscores.transpose(0, 1, 3, 2) @ q  # (B,H,T,Dh)

        def merge_heads(t):
            return t.transpose(0, 2, 1, 3).reshape(B, T, H * Dh)

        dx = self.q_proj.backward(merge_heads(dq))
        dx += self.k_proj.backward(merge_heads(dk))
        dx += self.v_proj.backward(merge_heads(dv))
        return dx

    def parameters(self):
        return (
            self.q_proj.parameters()
            + self.k_proj.parameters()
            + self.v_proj.parameters()
            + self.out_proj.parameters()
        )


def softmax_cross_entropy(logits, targets):
    """logits: (..., V) float array. targets: (...) int array.
    Returns (loss, dlogits) — a fused, numerically stable log-softmax + NLL
    with its analytic gradient (softmax(logits) - one_hot(targets)) / N.
    """
    shape = logits.shape
    V = shape[-1]
    flat_logits = logits.reshape(-1, V)
    flat_targets = targets.reshape(-1)
    N = flat_logits.shape[0]

    shifted = flat_logits - flat_logits.max(axis=-1, keepdims=True)
    logsumexp = np.log(np.exp(shifted).sum(axis=-1, keepdims=True))
    logprobs = shifted - logsumexp
    nll = -logprobs[np.arange(N), flat_targets]
    loss = nll.mean()

    probs = np.exp(logprobs)
    dlogits = probs.copy()
    dlogits[np.arange(N), flat_targets] -= 1.0
    dlogits /= N
    return loss, dlogits.reshape(shape)
