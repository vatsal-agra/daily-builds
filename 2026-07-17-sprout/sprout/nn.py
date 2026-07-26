"""A GPT-style decoder-only transformer, implemented from raw NumPy.

No autograd library is used anywhere. Every module below implements both
`forward` (which caches whatever it needs) and `backward` (which returns the
gradient w.r.t. its input and accumulates gradients for its own parameters
into `self.grads`). Correctness is not assumed — see gradcheck.py, which
verifies every module's analytic gradient against finite differences.
"""
import numpy as np


def softmax(x, axis=-1):
    x = x - np.max(x, axis=axis, keepdims=True)
    e = np.exp(x)
    return e / np.sum(e, axis=axis, keepdims=True)


class Module:
    def parameters(self):
        """Yield (name, param_array, grad_array) for this module and children."""
        for name, p in self.params.items():
            yield name, p, self.grads[name]
        for child_name, child in getattr(self, "_children", {}).items():
            for name, p, g in child.parameters():
                yield f"{child_name}.{name}", p, g

    def zero_grad(self):
        for _, _, g in self.parameters():
            g.fill(0.0)


class Linear(Module):
    def __init__(self, in_dim, out_dim, bias=True, std=0.02):
        self.params = {"W": np.random.randn(in_dim, out_dim).astype(np.float64) * std}
        self.grads = {"W": np.zeros_like(self.params["W"])}
        self.use_bias = bias
        if bias:
            self.params["b"] = np.zeros(out_dim)
            self.grads["b"] = np.zeros(out_dim)
        self._children = {}
        self._cache = None

    def forward(self, x):
        self._cache = x
        out = x @ self.params["W"]
        if self.use_bias:
            out = out + self.params["b"]
        return out

    def backward(self, dout):
        x = self._cache
        flat_x = x.reshape(-1, x.shape[-1])
        flat_dout = dout.reshape(-1, dout.shape[-1])
        self.grads["W"] += flat_x.T @ flat_dout
        if self.use_bias:
            self.grads["b"] += flat_dout.sum(axis=0)
        dx = dout @ self.params["W"].T
        return dx


class LayerNorm(Module):
    def __init__(self, dim, eps=1e-5):
        self.params = {"gamma": np.ones(dim), "beta": np.zeros(dim)}
        self.grads = {"gamma": np.zeros(dim), "beta": np.zeros(dim)}
        self.eps = eps
        self._children = {}
        self._cache = None

    def forward(self, x):
        mu = x.mean(axis=-1, keepdims=True)
        var = x.var(axis=-1, keepdims=True)
        std = np.sqrt(var + self.eps)
        xhat = (x - mu) / std
        out = self.params["gamma"] * xhat + self.params["beta"]
        self._cache = (xhat, std)
        return out

    def backward(self, dout):
        xhat, std = self._cache
        dim = xhat.shape[-1]
        self.grads["gamma"] += (dout * xhat).sum(axis=tuple(range(dout.ndim - 1)))
        self.grads["beta"] += dout.sum(axis=tuple(range(dout.ndim - 1)))

        dxhat = dout * self.params["gamma"]
        # standard layernorm backward: dx = (1/std) * (dxhat - mean(dxhat)
        #   - xhat * mean(dxhat * xhat))
        dx = (1.0 / std) * (
            dxhat
            - dxhat.mean(axis=-1, keepdims=True)
            - xhat * (dxhat * xhat).mean(axis=-1, keepdims=True)
        )
        return dx


class Embedding(Module):
    def __init__(self, num_embeddings, dim, std=0.02):
        self.params = {"table": np.random.randn(num_embeddings, dim).astype(np.float64) * std}
        self.grads = {"table": np.zeros_like(self.params["table"])}
        self._children = {}
        self._cache = None

    def forward(self, ids):
        self._cache = ids
        return self.params["table"][ids]

    def backward(self, dout):
        ids = self._cache
        flat_ids = ids.reshape(-1)
        flat_dout = dout.reshape(-1, dout.shape[-1])
        np.add.at(self.grads["table"], flat_ids, flat_dout)
        return None  # embeddings have no "input gradient" to propagate further


def gelu(x):
    c = np.sqrt(2.0 / np.pi)
    u = x + 0.044715 * x**3
    return 0.5 * x * (1.0 + np.tanh(c * u))


def gelu_grad(x):
    c = np.sqrt(2.0 / np.pi)
    u = x + 0.044715 * x**3
    t = np.tanh(c * u)
    dtanh = 1.0 - t**2
    du_dx = 1.0 + 3 * 0.044715 * x**2
    return 0.5 * (1.0 + t) + 0.5 * x * dtanh * c * du_dx


class MLP(Module):
    def __init__(self, dim, hidden_mult=4):
        self.fc1 = Linear(dim, dim * hidden_mult)
        self.fc2 = Linear(dim * hidden_mult, dim)
        self.params, self.grads = {}, {}
        self._children = {"fc1": self.fc1, "fc2": self.fc2}
        self._cache = None

    def forward(self, x):
        h = self.fc1.forward(x)
        a = gelu(h)
        self._cache = h
        out = self.fc2.forward(a)
        return out

    def backward(self, dout):
        h = self._cache
        da = self.fc2.backward(dout)
        dh = da * gelu_grad(h)
        dx = self.fc1.backward(dh)
        return dx


class CausalSelfAttention(Module):
    def __init__(self, dim, n_heads):
        assert dim % n_heads == 0
        self.dim = dim
        self.n_heads = n_heads
        self.head_dim = dim // n_heads
        self.qkv = Linear(dim, 3 * dim)
        self.proj = Linear(dim, dim)
        self.params, self.grads = {}, {}
        self._children = {"qkv": self.qkv, "proj": self.proj}
        self._cache = None

    def _split_heads(self, x, B, T):
        # (B, T, C) -> (B, H, T, D)
        return x.reshape(B, T, self.n_heads, self.head_dim).transpose(0, 2, 1, 3)

    def _merge_heads(self, x, B, T):
        # (B, H, T, D) -> (B, T, C)
        return x.transpose(0, 2, 1, 3).reshape(B, T, self.dim)

    def forward(self, x):
        B, T, C = x.shape
        qkv = self.qkv.forward(x)  # (B, T, 3C)
        q, k, v = np.split(qkv, 3, axis=-1)
        q = self._split_heads(q, B, T)
        k = self._split_heads(k, B, T)
        v = self._split_heads(v, B, T)

        scale = 1.0 / np.sqrt(self.head_dim)
        raw_scores = np.einsum("bhid,bhjd->bhij", q, k)
        scores = raw_scores * scale

        causal_mask = np.triu(np.ones((T, T), dtype=bool), k=1)
        scores = np.where(causal_mask, -np.inf, scores)

        attn = softmax(scores, axis=-1)
        out_heads = np.einsum("bhij,bhjd->bhid", attn, v)  # (B, H, T, D)
        out = self._merge_heads(out_heads, B, T)

        self._cache = (q, k, v, attn, scale, B, T)
        y = self.proj.forward(out)
        return y

    def backward(self, dy):
        q, k, v, attn, scale, B, T = self._cache
        dout = self.proj.backward(dy)  # (B, T, C)
        dout_heads = self._split_heads(dout, B, T)  # (B, H, T, D)

        dv = np.einsum("bhij,bhid->bhjd", attn, dout_heads)
        dattn = np.einsum("bhid,bhjd->bhij", dout_heads, v)

        # softmax backward (row-wise over last axis)
        dscores = attn * (dattn - np.sum(attn * dattn, axis=-1, keepdims=True))
        draw = dscores * scale

        dq = np.einsum("bhij,bhjd->bhid", draw, k)
        dk = np.einsum("bhij,bhid->bhjd", draw, q)

        dq = self._merge_heads(dq, B, T)
        dk = self._merge_heads(dk, B, T)
        dv = self._merge_heads(dv, B, T)
        dqkv = np.concatenate([dq, dk, dv], axis=-1)
        dx = self.qkv.backward(dqkv)
        return dx


class Block(Module):
    def __init__(self, dim, n_heads):
        self.ln1 = LayerNorm(dim)
        self.attn = CausalSelfAttention(dim, n_heads)
        self.ln2 = LayerNorm(dim)
        self.mlp = MLP(dim)
        self.params, self.grads = {}, {}
        self._children = {"ln1": self.ln1, "attn": self.attn, "ln2": self.ln2, "mlp": self.mlp}

    def forward(self, x):
        a = self.attn.forward(self.ln1.forward(x))
        x1 = x + a
        m = self.mlp.forward(self.ln2.forward(x1))
        x2 = x1 + m
        return x2

    def backward(self, dout):
        dm = dout
        dx1_res = dout
        dln2_out = self.mlp.backward(dm)
        dx1_mlp = self.ln2.backward(dln2_out)
        dx1 = dx1_res + dx1_mlp

        da = dx1
        dx0_res = dx1
        dln1_out = self.attn.backward(da)
        dx0_attn = self.ln1.backward(dln1_out)
        dx0 = dx0_res + dx0_attn
        return dx0


class GPT(Module):
    def __init__(self, vocab_size, block_size, n_layer, n_head, n_embd):
        self.vocab_size = vocab_size
        self.block_size = block_size
        self.n_embd = n_embd

        self.wte = Embedding(vocab_size, n_embd)
        self.wpe_table = np.random.randn(block_size, n_embd).astype(np.float64) * 0.02
        self.wpe_grad = np.zeros_like(self.wpe_table)

        self.blocks = [Block(n_embd, n_head) for _ in range(n_layer)]
        self.ln_f = LayerNorm(n_embd)
        self.head = Linear(n_embd, vocab_size, bias=False)

        self.params, self.grads = {}, {}
        self._children = {"wte": self.wte, "ln_f": self.ln_f, "head": self.head}
        for i, blk in enumerate(self.blocks):
            self._children[f"block{i}"] = blk

        self._cache = None

    def parameters(self):
        for name, p, g in super().parameters():
            yield name, p, g
        yield "wpe", self.wpe_table, self.wpe_grad

    def zero_grad(self):
        super().zero_grad()
        self.wpe_grad.fill(0.0)

    def num_params(self):
        return sum(p.size for _, p, _ in self.parameters())

    def forward(self, idx):
        B, T = idx.shape
        assert T <= self.block_size, f"sequence length {T} exceeds block_size {self.block_size}"
        tok_emb = self.wte.forward(idx)  # (B, T, C)
        pos_emb = self.wpe_table[:T]  # (T, C)
        x = tok_emb + pos_emb
        for blk in self.blocks:
            x = blk.forward(x)
        x = self.ln_f.forward(x)
        logits = self.head.forward(x)
        self._cache = T
        return logits

    def backward(self, dlogits):
        T = self._cache
        dx = self.head.backward(dlogits)
        dx = self.ln_f.backward(dx)
        for blk in reversed(self.blocks):
            dx = blk.backward(dx)
        # dx: (B, T, C), split gradient to token emb and positional emb
        self.wte.backward(dx)
        self.wpe_grad[:T] += dx.sum(axis=0)


def cross_entropy_loss(logits, targets):
    """logits: (B, T, V) float, targets: (B, T) int. Returns (loss, dlogits)."""
    B, T, V = logits.shape
    probs = softmax(logits, axis=-1)
    b_idx = np.arange(B)[:, None]
    t_idx = np.arange(T)[None, :]
    correct_logprobs = np.log(np.clip(probs[b_idx, t_idx, targets], 1e-12, None))
    loss = -correct_logprobs.mean()

    dlogits = probs.copy()
    dlogits[b_idx, t_idx, targets] -= 1.0
    dlogits /= B * T
    return loss, dlogits
