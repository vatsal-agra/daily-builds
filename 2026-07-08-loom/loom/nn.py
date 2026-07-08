"""Transformer building blocks, composed entirely from loom.tensor primitives.

Every module's backward pass is "free" -- it falls out of composing
autograd primitives, exactly the way a real framework's nn.Module library
works on top of its tensor core.
"""
import math

import numpy as np

from .tensor import Tensor, concatenate, no_grad

GELU_CONST = math.sqrt(2.0 / math.pi)


def gelu(x):
    """Tanh-approximation GELU, built from primitive ops (tanh has a hand-
    derived backward in tensor.py; everything else composes through it)."""
    inner = (x + x.pow(3) * 0.044715) * GELU_CONST
    return x * 0.5 * (inner.tanh() + 1.0)


class Module:
    def parameters(self):
        return [p for _, p in self.named_parameters()]

    def named_parameters(self, prefix=""):
        out = []
        for name, val in vars(self).items():
            full = f"{prefix}{name}"
            if isinstance(val, Tensor) and val.requires_grad:
                out.append((full, val))
            elif isinstance(val, Module):
                out.extend(val.named_parameters(prefix=full + "."))
            elif isinstance(val, (list, tuple)):
                for i, item in enumerate(val):
                    if isinstance(item, Module):
                        out.extend(item.named_parameters(prefix=f"{full}.{i}."))
        return out

    def zero_grad(self):
        for p in self.parameters():
            p.grad = None

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)


def _param(*shape, std=0.02):
    return Tensor(np.random.randn(*shape) * std, requires_grad=True)


def _zeros(*shape):
    return Tensor(np.zeros(shape), requires_grad=True)


def _ones(*shape):
    return Tensor(np.ones(shape), requires_grad=True)


class Linear(Module):
    def __init__(self, n_in, n_out, bias=True, std=0.02):
        self.weight = _param(n_in, n_out, std=std)
        self.bias = _zeros(n_out) if bias else None

    def forward(self, x):
        out = x @ self.weight
        if self.bias is not None:
            out = out + self.bias
        return out


class Embedding(Module):
    def __init__(self, num_embeddings, dim, std=0.02):
        self.weight = _param(num_embeddings, dim, std=std)

    def forward(self, idx):
        return self.weight.embedding(idx)


class LayerNorm(Module):
    def __init__(self, dim, eps=1e-5):
        self.gamma = _ones(dim)
        self.beta = _zeros(dim)
        self.eps = eps

    def forward(self, x):
        mu = x.mean(axis=-1, keepdims=True)
        xmu = x - mu
        var = (xmu * xmu).mean(axis=-1, keepdims=True)
        std = (var + self.eps).sqrt()
        xhat = xmu / std
        return xhat * self.gamma + self.beta


def causal_mask(T, past_len=0):
    """Mask of shape (1, 1, T, past_len + T): query position i (absolute
    position past_len + i) may attend to key position j iff j <= past_len + i.
    past_len=0 reduces to the standard upper-triangular causal mask."""
    T_kv = past_len + T
    rows = np.arange(T).reshape(T, 1) + past_len
    cols = np.arange(T_kv).reshape(1, T_kv)
    m = np.where(cols <= rows, 0.0, -1e9)
    return m.reshape(1, 1, T, T_kv)


class CausalSelfAttention(Module):
    def __init__(self, n_embd, n_head, block_size):
        assert n_embd % n_head == 0
        self.n_head = n_head
        self.n_embd = n_embd
        self.head_dim = n_embd // n_head
        self.block_size = block_size
        self.c_attn = Linear(n_embd, 3 * n_embd)
        self.c_proj = Linear(n_embd, n_embd)
        self.last_attn = None

    def _split_heads(self, x, B, T):
        x = x.reshape(B, T, self.n_head, self.head_dim)
        return x.transpose(0, 2, 1, 3)  # (B, n_head, T, head_dim)

    def forward(self, x, kv_cache=None):
        """x: (B, T, n_embd). If kv_cache is given (a dict with 'k','v' numpy
        arrays of shape (B, n_head, T_past, head_dim)), only the new T tokens
        of x are attended, but they attend over the full past+new key/value
        sequence -- the KV-cache incremental-decoding path. Returns
        (out, new_kv_cache)."""
        B, T, C = x.shape
        qkv = self.c_attn(x)
        q = qkv[:, :, 0:C]
        k = qkv[:, :, C:2 * C]
        v = qkv[:, :, 2 * C:3 * C]
        q = self._split_heads(q, B, T)
        k = self._split_heads(k, B, T)
        v = self._split_heads(v, B, T)

        if kv_cache is not None and kv_cache.get("k") is not None:
            # inference-only path: cache holds plain numpy arrays, no grad
            k_full = np.concatenate([kv_cache["k"], k.data], axis=2)
            v_full = np.concatenate([kv_cache["v"], v.data], axis=2)
            k = Tensor(k_full)
            v = Tensor(v_full)
            new_cache = {"k": k_full, "v": v_full}
        elif kv_cache is not None:
            new_cache = {"k": k.data, "v": v.data}
        else:
            new_cache = None

        scale = 1.0 / math.sqrt(self.head_dim)
        scores = (q @ k.transpose(0, 1, 3, 2)) * scale  # (B, n_head, T, T_kv)
        T_kv = scores.shape[-1]
        past_len = T_kv - T
        scores = scores + Tensor(causal_mask(T, past_len=past_len))
        attn = scores.softmax(axis=-1)
        self.last_attn = attn.data  # (B, n_head, T, T_kv); read by the viz module
        out = attn @ v  # (B, n_head, T, head_dim)
        out = out.transpose(0, 2, 1, 3).reshape(B, T, C)
        out = self.c_proj(out)
        return out, new_cache


class MLP(Module):
    def __init__(self, n_embd, expansion=4):
        self.c_fc = Linear(n_embd, expansion * n_embd)
        self.c_proj = Linear(expansion * n_embd, n_embd)

    def forward(self, x):
        return self.c_proj(gelu(self.c_fc(x)))


class Block(Module):
    def __init__(self, n_embd, n_head, block_size):
        self.ln1 = LayerNorm(n_embd)
        self.attn = CausalSelfAttention(n_embd, n_head, block_size)
        self.ln2 = LayerNorm(n_embd)
        self.mlp = MLP(n_embd)

    def forward(self, x, kv_cache=None):
        attn_out, new_cache = self.attn(self.ln1(x), kv_cache=kv_cache)
        x = x + attn_out
        x = x + self.mlp(self.ln2(x))
        return x, new_cache


class GPT(Module):
    def __init__(self, vocab_size, n_embd, n_head, n_layer, block_size):
        self.vocab_size = vocab_size
        self.n_embd = n_embd
        self.n_head = n_head
        self.n_layer = n_layer
        self.block_size = block_size

        self.wte = Embedding(vocab_size, n_embd)
        self.wpe = Embedding(block_size, n_embd)
        self.blocks = [Block(n_embd, n_head, block_size) for _ in range(n_layer)]
        self.ln_f = LayerNorm(n_embd)

    def forward(self, idx, targets=None, kv_caches=None):
        """idx: int numpy array (B, T). targets: int numpy array (B, T) or
        None. kv_caches: list of per-block cache dicts (or None) for
        incremental decoding, mutated in place with the new K/V.
        Returns (logits, loss_or_None)."""
        idx = np.asarray(idx)
        B, T = idx.shape
        if kv_caches is not None and kv_caches[0].get("k") is not None:
            past_len = kv_caches[0]["k"].shape[2]
        else:
            past_len = 0
        assert past_len + T <= self.block_size, "sequence length exceeds block_size"

        tok_emb = self.wte(idx)  # (B, T, n_embd)
        positions = np.arange(past_len, past_len + T)
        pos_emb = self.wpe(positions).reshape(1, T, self.n_embd)
        x = tok_emb + pos_emb

        for i, block in enumerate(self.blocks):
            cache_i = kv_caches[i] if kv_caches is not None else None
            x, new_cache = block(x, kv_cache=cache_i)
            if kv_caches is not None:
                kv_caches[i] = new_cache

        x = self.ln_f(x)
        logits = x @ self.wte.weight.T  # weight-tied output head, (B,T,vocab)

        loss = None
        if targets is not None:
            targets = np.asarray(targets)
            loss = logits.reshape(B * T, self.vocab_size).cross_entropy(
                targets.reshape(B * T)
            )
        return logits, loss

    def num_params(self):
        return sum(p.data.size for p in self.parameters())

    def new_kv_caches(self):
        return [{"k": None, "v": None} for _ in range(self.n_layer)]

    def generate(self, idx, max_new_tokens, temperature=1.0, top_k=None, rng=None,
                 use_kv_cache=True):
        """idx: int numpy array (B, T) prompt. Returns (B, T+max_new_tokens)."""
        rng = rng or np.random.default_rng()
        idx = np.array(idx, dtype=np.int64)
        if use_kv_cache:
            # position embeddings only cover [0, block_size); the KV-cached
            # path never forgets earlier positions (unlike the sliding-window
            # non-cached path below), so the fixed context window bounds how
            # many new tokens we can generate this call.
            max_new_tokens = max(0, min(max_new_tokens, self.block_size - idx.shape[1]))
        with no_grad():
            kv_caches = self.new_kv_caches() if use_kv_cache else None
            first = True
            for _ in range(max_new_tokens):
                if use_kv_cache and not first:
                    step_idx = idx[:, -1:]
                else:
                    idx_cond = idx[:, -self.block_size:]
                    step_idx = idx_cond
                logits, _ = self.forward(step_idx, kv_caches=kv_caches)
                first = False
                last_logits = logits.data[:, -1, :] / max(temperature, 1e-8)
                if top_k is not None:
                    k = min(top_k, last_logits.shape[-1])
                    kth = np.partition(last_logits, -k, axis=-1)[:, -k:].min(axis=-1, keepdims=True)
                    last_logits = np.where(last_logits < kth, -np.inf, last_logits)
                m = last_logits.max(axis=-1, keepdims=True)
                probs = np.exp(last_logits - m)
                probs /= probs.sum(axis=-1, keepdims=True)
                next_tok = np.array(
                    [rng.choice(len(p), p=p) for p in probs]
                ).reshape(-1, 1)
                idx = np.concatenate([idx, next_tok], axis=1)
        return idx
