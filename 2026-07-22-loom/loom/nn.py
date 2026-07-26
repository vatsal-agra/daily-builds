"""The transformer architecture, composed entirely from loom.autograd primitives.

Nothing in this file imports torch/tensorflow/jax. Every layer below is
just Python + the Tensor ops in autograd.py, wired together the same way
you'd wire up nn.Module subclasses in a real framework -- except every one
of these forward passes is differentiated by our own tape, not someone
else's autograd.
"""

import numpy as np

from .autograd import Tensor, Parameter, cat, softmax, layer_norm, gelu, masked_fill, embedding_lookup


class Module:
    def parameters(self):
        params = []
        for value in self.__dict__.values():
            if isinstance(value, Parameter):
                params.append(value)
            elif isinstance(value, Module):
                params.extend(value.parameters())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, Module):
                        params.extend(item.parameters())
        return params

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)


class Linear(Module):
    def __init__(self, in_features, out_features, rng, bias=True):
        scale = 1.0 / np.sqrt(in_features)
        self.weight = Parameter(rng.uniform(-scale, scale, size=(in_features, out_features)))
        self.bias = Parameter(np.zeros(out_features)) if bias else None

    def forward(self, x):
        out = x.matmul(self.weight)
        if self.bias is not None:
            out = out + self.bias
        return out


class Embedding(Module):
    def __init__(self, num_embeddings, dim, rng, std=0.02):
        self.weight = Parameter(rng.normal(0.0, std, size=(num_embeddings, dim)))

    def forward(self, indices):
        return embedding_lookup(self.weight, indices)


class LayerNorm(Module):
    def __init__(self, dim):
        self.gamma = Parameter(np.ones(dim))
        self.beta = Parameter(np.zeros(dim))

    def forward(self, x):
        return layer_norm(x, self.gamma, self.beta)


class CausalSelfAttention(Module):
    """Multi-head causal self-attention with an optional KV-cache."""

    def __init__(self, dim, n_heads, rng):
        assert dim % n_heads == 0
        self.dim = dim
        self.n_heads = n_heads
        self.head_dim = dim // n_heads
        self.wq = Linear(dim, dim, rng)
        self.wk = Linear(dim, dim, rng)
        self.wv = Linear(dim, dim, rng)
        self.wo = Linear(dim, dim, rng)

    def _split_heads(self, x, B, T):
        # (B, T, D) -> (B, H, T, Dh)
        return x.reshape(B, T, self.n_heads, self.head_dim).transpose(0, 2, 1, 3)

    def forward(self, x, cache=None, pos_offset=0):
        """``x``: Tensor (B, T, D) holding the new tokens starting at absolute
        position ``pos_offset``. If ``cache`` is a dict, past K/V (from
        absolute positions [0, pos_offset)) are read from and written back
        into it -- ``x`` need not be a single token; priming a cache with a
        whole prompt in one call (T > 1) is also supported."""
        B, T, D = x.data.shape
        q = self._split_heads(self.wq(x), B, T)
        k_new = self._split_heads(self.wk(x), B, T)
        v_new = self._split_heads(self.wv(x), B, T)

        if cache is not None and cache.get("k") is not None:
            k = cat([cache["k"], k_new], axis=2)
            v = cat([cache["v"], v_new], axis=2)
        else:
            k, v = k_new, v_new

        if cache is not None:
            cache["k"], cache["v"] = k, v

        T_k = k.data.shape[2]
        scores = q.matmul(k.transpose(0, 1, 3, 2)) * (1.0 / np.sqrt(self.head_dim))

        # Causal mask built from absolute positions: query i (absolute
        # position pos_offset+i) may attend to key j (absolute position j)
        # iff j <= pos_offset+i. This covers every case uniformly -- a plain
        # forward pass (pos_offset=0, T==T_k), priming a cache with a whole
        # prompt in one shot (T==T_k, pos_offset=0), and single-token
        # incremental decoding (T=1, T_k=pos_offset+1) -- so there is no
        # special-cased "skip the mask because we have a cache" branch to
        # get wrong.
        query_pos = np.arange(pos_offset, pos_offset + T)
        key_pos = np.arange(T_k)
        future = key_pos[None, :] > query_pos[:, None]
        if future.any():
            scores = masked_fill(scores, future[None, None, :, :], -1e9)

        attn = softmax(scores, axis=-1)
        out = attn.matmul(v)  # (B, H, T, Dh)
        out = out.transpose(0, 2, 1, 3).reshape(B, T, D)
        return self.wo(out), attn


class FeedForward(Module):
    def __init__(self, dim, hidden_mult, rng):
        self.fc1 = Linear(dim, dim * hidden_mult, rng)
        self.fc2 = Linear(dim * hidden_mult, dim, rng)

    def forward(self, x):
        return self.fc2(gelu(self.fc1(x)))


class TransformerBlock(Module):
    def __init__(self, dim, n_heads, hidden_mult, rng):
        self.ln1 = LayerNorm(dim)
        self.attn = CausalSelfAttention(dim, n_heads, rng)
        self.ln2 = LayerNorm(dim)
        self.ff = FeedForward(dim, hidden_mult, rng)

    def forward(self, x, cache=None, pos_offset=0):
        attn_out, attn_weights = self.attn(self.ln1(x), cache=cache, pos_offset=pos_offset)
        x = x + attn_out
        x = x + self.ff(self.ln2(x))
        return x, attn_weights


class LoomModel(Module):
    """A decoder-only transformer language model (GPT-family architecture)."""

    def __init__(self, vocab_size, dim, n_layers, n_heads, max_seq_len, hidden_mult=4, seed=0):
        rng = np.random.default_rng(seed)
        self.vocab_size = vocab_size
        self.dim = dim
        self.max_seq_len = max_seq_len
        self.tok_emb = Embedding(vocab_size, dim, rng)
        self.pos_emb = Embedding(max_seq_len, dim, rng)
        self.blocks = [TransformerBlock(dim, n_heads, hidden_mult, rng) for _ in range(n_layers)]
        self.ln_f = LayerNorm(dim)
        # weight-tied output head: logits = h @ tok_emb.T (no separate projection matrix)

    def forward(self, token_ids, cache=None, pos_offset=0):
        """``token_ids``: int ndarray (B, T). Returns logits Tensor (B, T, V) and
        a list of per-layer attention-weight Tensors for visualization."""
        B, T = token_ids.shape
        tok = self.tok_emb(token_ids)
        positions = np.arange(pos_offset, pos_offset + T)
        pos = self.pos_emb(positions)[None, :, :]
        x = tok + pos

        attn_maps = []
        for i, block in enumerate(self.blocks):
            block_cache = None if cache is None else cache[i]
            x, attn_w = block(x, cache=block_cache, pos_offset=pos_offset)
            attn_maps.append(attn_w)
        x = self.ln_f(x)

        logits = x.matmul(self.tok_emb.weight.transpose(1, 0))
        return logits, attn_maps

    def new_cache(self):
        return [{"k": None, "v": None} for _ in self.blocks]

    def parameters(self):
        params = self.tok_emb.parameters() + self.pos_emb.parameters()
        for block in self.blocks:
            params += block.parameters()
        params += self.ln_f.parameters()
        return params

    def num_params(self):
        return sum(p.data.size for p in self.parameters())
