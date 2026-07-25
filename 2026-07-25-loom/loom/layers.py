"""
Transformer building blocks with hand-derived forward() AND backward().

No autograd anywhere: every backward() below is the analytic gradient,
written out by hand, and is checked against numerical (finite-difference)
gradients in tests/test_gradcheck.py. Each layer is a small stateful object:
forward() caches whatever backward() needs, backward() returns dL/dinput
and stores dL/dparam in self.grads.

Shapes follow the GPT-2 convention: (B, T, C) = (batch, sequence, d_model).
"""
import numpy as np

from .tensor_ops import gelu_backward, gelu_forward, softmax, softmax_backward


class Linear:
    def __init__(self, n_in, n_out, rng, std=0.02, bias=True):
        self.W = rng.normal(0.0, std, size=(n_in, n_out)).astype(np.float64)
        self.b = np.zeros(n_out, dtype=np.float64) if bias else None
        self.grads = {}
        self._cache = None

    def params(self):
        p = {"W": self.W}
        if self.b is not None:
            p["b"] = self.b
        return p

    def forward(self, x):
        # x: (..., n_in) -> (..., n_out)
        shape = x.shape
        x2 = x.reshape(-1, shape[-1])
        y2 = x2 @ self.W
        if self.b is not None:
            y2 = y2 + self.b
        self._cache = x2
        return y2.reshape(*shape[:-1], self.W.shape[1])

    def backward(self, dout):
        shape = dout.shape
        dout2 = dout.reshape(-1, shape[-1])
        x2 = self._cache
        self.grads["W"] = x2.T @ dout2
        if self.b is not None:
            self.grads["b"] = dout2.sum(axis=0)
        dx2 = dout2 @ self.W.T
        return dx2.reshape(*shape[:-1], self.W.shape[0])


class LayerNorm:
    def __init__(self, n, eps=1e-5):
        self.gamma = np.ones(n, dtype=np.float64)
        self.beta = np.zeros(n, dtype=np.float64)
        self.eps = eps
        self.grads = {}
        self._cache = None

    def params(self):
        return {"gamma": self.gamma, "beta": self.beta}

    def forward(self, x):
        mu = x.mean(axis=-1, keepdims=True)
        var = x.var(axis=-1, keepdims=True)
        std = np.sqrt(var + self.eps)
        xhat = (x - mu) / std
        y = self.gamma * xhat + self.beta
        self._cache = (xhat, std)
        return y

    def backward(self, dout):
        xhat, std = self._cache
        N = dout.shape[-1]
        self.grads["gamma"] = np.sum(dout * xhat, axis=tuple(range(dout.ndim - 1)))
        self.grads["beta"] = np.sum(dout, axis=tuple(range(dout.ndim - 1)))

        dxhat = dout * self.gamma
        # standard LayerNorm backward: dL/dx from dL/dxhat
        term1 = dxhat
        term2 = np.mean(dxhat, axis=-1, keepdims=True)
        term3 = xhat * np.mean(dxhat * xhat, axis=-1, keepdims=True)
        dx = (term1 - term2 - term3) / std
        return dx


class GELU:
    def __init__(self):
        self._cache = None
        self.grads = {}

    def params(self):
        return {}

    def forward(self, x):
        y, cache = gelu_forward(x)
        self._cache = cache
        return y

    def backward(self, dout):
        return gelu_backward(dout, self._cache)


class Embedding:
    def __init__(self, vocab_size, n_ctx, n_embd, rng, std=0.02):
        self.wte = rng.normal(0.0, std, size=(vocab_size, n_embd)).astype(np.float64)
        self.wpe = rng.normal(0.0, std, size=(n_ctx, n_embd)).astype(np.float64)
        self.grads = {}
        self._cache = None

    def params(self):
        return {"wte": self.wte, "wpe": self.wpe}

    def forward(self, idx):
        B, T = idx.shape
        self._cache = idx
        tok = self.wte[idx]
        pos = self.wpe[:T][None, :, :]
        return tok + pos

    def backward(self, dout):
        idx = self._cache
        B, T, C = dout.shape
        dwte = np.zeros_like(self.wte)
        np.add.at(dwte, idx.reshape(-1), dout.reshape(-1, C))
        self.grads["wte"] = dwte
        dwpe = np.zeros_like(self.wpe)
        dwpe[:T] = dout.sum(axis=0)
        self.grads["wpe"] = dwpe
        return None  # embedding has no "input" gradient to propagate


class CausalSelfAttention:
    def __init__(self, n_embd, n_head, n_ctx, rng, std=0.02):
        assert n_embd % n_head == 0, (
            f"n_embd ({n_embd}) must be divisible by n_head ({n_head}) so every "
            f"head gets an equal-sized slice of the embedding"
        )
        self.n_embd = n_embd
        self.n_head = n_head
        self.head_dim = n_embd // n_head
        self.c_attn = Linear(n_embd, 3 * n_embd, rng, std=std)
        self.c_proj = Linear(n_embd, n_embd, rng, std=std)
        causal = np.tril(np.ones((n_ctx, n_ctx), dtype=bool))
        self.mask = causal
        self.grads = {}
        self._cache = None

    def params(self):
        p = {}
        for name, sub in (("c_attn", self.c_attn), ("c_proj", self.c_proj)):
            for k, v in sub.params().items():
                p[f"{name}.{k}"] = v
        return p

    def _split_heads(self, x, B, T):
        # (B,T,C) -> (B,H,T,hd)
        x = x.reshape(B, T, self.n_head, self.head_dim)
        return x.transpose(0, 2, 1, 3)

    def _merge_heads(self, x, B, T):
        # (B,H,T,hd) -> (B,T,C)
        x = x.transpose(0, 2, 1, 3)
        return x.reshape(B, T, self.n_embd)

    def forward(self, x, kv_cache=None):
        B, T, C = x.shape
        qkv = self.c_attn.forward(x)  # (B,T,3C)
        q, k, v = np.split(qkv, 3, axis=-1)
        q = self._split_heads(q, B, T)
        k = self._split_heads(k, B, T)
        v = self._split_heads(v, B, T)

        if kv_cache is not None:
            past_k, past_v = kv_cache
            if past_k is not None:
                k = np.concatenate([past_k, k], axis=2)
                v = np.concatenate([past_v, v], axis=2)
            new_cache = (k, v)
        else:
            new_cache = None

        Tk = k.shape[2]
        scale = 1.0 / np.sqrt(self.head_dim)
        scores = (q @ k.transpose(0, 1, 3, 2)) * scale  # (B,H,T,Tk)

        if kv_cache is None:
            mask = self.mask[:T, :T]
            scores = np.where(mask[None, None, :, :], scores, -1e10)
        # when using kv_cache, every past position is causally valid and the
        # single new query position attends to all of them: no mask needed.

        p = softmax(scores, axis=-1)
        out = p @ v  # (B,H,T,hd)
        merged = self._merge_heads(out, B, T)
        y = self.c_proj.forward(merged)

        if kv_cache is not None:
            return y, new_cache

        self._cache = (B, T, q, k, v, p, scale)
        return y

    def backward(self, dout):
        B, T, q, k, v, p, scale = self._cache
        dmerged = self.c_proj.backward(dout)
        dout_heads = dmerged.reshape(B, T, self.n_head, self.head_dim).transpose(0, 2, 1, 3)

        dp = dout_heads @ v.transpose(0, 1, 3, 2)  # (B,H,T,Tk)
        dv = p.transpose(0, 1, 3, 2) @ dout_heads  # (B,H,Tk,hd)

        dscores = softmax_backward(dp, p, axis=-1)
        dscores = dscores * scale

        dq = dscores @ k  # (B,H,T,hd)
        dk = dscores.transpose(0, 1, 3, 2) @ q  # (B,H,Tk,hd)

        dq = self._merge_heads(dq, B, T)
        dk = self._merge_heads(dk, B, T)
        dv = self._merge_heads(dv, B, T)
        dqkv = np.concatenate([dq, dk, dv], axis=-1)

        dx = self.c_attn.backward(dqkv)
        self.grads = {}
        for name, sub in (("c_attn", self.c_attn), ("c_proj", self.c_proj)):
            for k2, v2 in sub.grads.items():
                self.grads[f"{name}.{k2}"] = v2
        return dx


class MLP:
    def __init__(self, n_embd, n_hidden, rng, std=0.02):
        self.fc1 = Linear(n_embd, n_hidden, rng, std=std)
        self.gelu = GELU()
        self.fc2 = Linear(n_hidden, n_embd, rng, std=std)
        self.grads = {}

    def params(self):
        p = {}
        for name, sub in (("fc1", self.fc1), ("fc2", self.fc2)):
            for k, v in sub.params().items():
                p[f"{name}.{k}"] = v
        return p

    def forward(self, x):
        h = self.fc1.forward(x)
        h = self.gelu.forward(h)
        return self.fc2.forward(h)

    def backward(self, dout):
        dh = self.fc2.backward(dout)
        dh = self.gelu.backward(dh)
        dx = self.fc1.backward(dh)
        self.grads = {}
        for name, sub in (("fc1", self.fc1), ("fc2", self.fc2)):
            for k, v in sub.grads.items():
                self.grads[f"{name}.{k}"] = v
        return dx


class Block:
    """Pre-norm GPT-2-style transformer block: x + attn(ln1(x)); x + mlp(ln2(x))."""

    def __init__(self, n_embd, n_head, n_ctx, n_hidden, rng, std=0.02):
        self.ln1 = LayerNorm(n_embd)
        self.attn = CausalSelfAttention(n_embd, n_head, n_ctx, rng, std=std)
        self.ln2 = LayerNorm(n_embd)
        self.mlp = MLP(n_embd, n_hidden, rng, std=std)
        self.grads = {}

    def params(self):
        p = {}
        for name, sub in (("ln1", self.ln1), ("attn", self.attn), ("ln2", self.ln2), ("mlp", self.mlp)):
            for k, v in sub.params().items():
                p[f"{name}.{k}"] = v
        return p

    def forward(self, x, kv_cache=None):
        if kv_cache is not None:
            a_in = self.ln1.forward(x)
            a_out, new_cache = self.attn.forward(a_in, kv_cache=kv_cache)
            x = x + a_out
            m_in = self.ln2.forward(x)
            m_out = self.mlp.forward(m_in)
            x = x + m_out
            return x, new_cache

        a_in = self.ln1.forward(x)
        a_out = self.attn.forward(a_in)
        x1 = x + a_out
        m_in = self.ln2.forward(x1)
        m_out = self.mlp.forward(m_in)
        x2 = x1 + m_out
        return x2

    def backward(self, dout):
        # x2 = x1 + mlp(ln2(x1))
        dm_out = dout
        dx1_res = dout
        dm_in = self.mlp.backward(dm_out)
        dx1_ln = self.ln2.backward(dm_in)
        dx1 = dx1_res + dx1_ln

        # x1 = x + attn(ln1(x))
        da_out = dx1
        dx_res = dx1
        da_in = self.attn.backward(da_out)
        dx_ln = self.ln1.backward(da_in)
        dx = dx_res + dx_ln

        self.grads = {}
        for name, sub in (("ln1", self.ln1), ("attn", self.attn), ("ln2", self.ln2), ("mlp", self.mlp)):
            for k, v in sub.grads.items():
                self.grads[f"{name}.{k}"] = v
        return dx
