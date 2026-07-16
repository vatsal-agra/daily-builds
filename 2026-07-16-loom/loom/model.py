"""A decoder-only, GPT-style Transformer, built entirely out of the
Tensor ops in loom/tensor.py. No `torch.nn` anywhere.
"""
from __future__ import annotations

import math
import numpy as np

from loom.tensor import Tensor, cat, embedding, layer_norm, gelu, softmax

_RNG = np.random.default_rng(1234)


def _param(shape, scale) -> Tensor:
    return Tensor(_RNG.normal(0.0, scale, size=shape), requires_grad=True)


class Linear:
    def __init__(self, in_features: int, out_features: int, bias: bool = True):
        self.W = _param((in_features, out_features), scale=1.0 / math.sqrt(in_features))
        self.b = Tensor(np.zeros(out_features), requires_grad=True) if bias else None

    def __call__(self, x: Tensor) -> Tensor:
        out = x @ self.W
        if self.b is not None:
            out = out + self.b
        return out

    def parameters(self):
        return [self.W] + ([self.b] if self.b is not None else [])


class LayerNorm:
    def __init__(self, dim: int):
        self.gamma = Tensor(np.ones(dim), requires_grad=True)
        self.beta = Tensor(np.zeros(dim), requires_grad=True)

    def __call__(self, x: Tensor) -> Tensor:
        return layer_norm(x, self.gamma, self.beta)

    def parameters(self):
        return [self.gamma, self.beta]


class CausalSelfAttention:
    def __init__(self, d_model: int, n_head: int, block_size: int):
        assert d_model % n_head == 0, "d_model must be divisible by n_head"
        self.d_model, self.n_head = d_model, n_head
        self.head_size = d_model // n_head
        self.q_proj = Linear(d_model, d_model)
        self.k_proj = Linear(d_model, d_model)
        self.v_proj = Linear(d_model, d_model)
        self.out_proj = Linear(d_model, d_model)
        # additive causal mask: 0 where allowed, -inf where disallowed (future tokens)
        mask = np.triu(np.full((block_size, block_size), -1e9), k=1)
        self._mask_full = mask
        self.last_attn = None  # populated on forward when capture_attn=True

    def _split_heads(self, x: Tensor, B: int, T: int) -> Tensor:
        return x.reshape(B, T, self.n_head, self.head_size).permute(0, 2, 1, 3)

    def __call__(self, x: Tensor, capture_attn: bool = False) -> Tensor:
        B, T, C = x.shape
        q = self._split_heads(self.q_proj(x), B, T)  # (B, nh, T, hs)
        k = self._split_heads(self.k_proj(x), B, T)
        v = self._split_heads(self.v_proj(x), B, T)

        scale = 1.0 / math.sqrt(self.head_size)
        scores = (q @ k.permute(0, 1, 3, 2)) * scale  # (B, nh, T, T)
        mask = Tensor(self._mask_full[:T, :T])
        scores = scores + mask
        attn = softmax(scores, axis=-1)
        if capture_attn:
            self.last_attn = attn.data.copy()  # (B, nh, T, T), detached snapshot
        out = attn @ v  # (B, nh, T, hs)
        out = out.permute(0, 2, 1, 3).reshape(B, T, C)
        return self.out_proj(out)

    def parameters(self):
        ps = []
        for layer in (self.q_proj, self.k_proj, self.v_proj, self.out_proj):
            ps += layer.parameters()
        return ps


class MLP:
    def __init__(self, d_model: int, expansion: int = 4):
        self.fc = Linear(d_model, expansion * d_model)
        self.proj = Linear(expansion * d_model, d_model)

    def __call__(self, x: Tensor) -> Tensor:
        return self.proj(gelu(self.fc(x)))

    def parameters(self):
        return self.fc.parameters() + self.proj.parameters()


class Block:
    def __init__(self, d_model: int, n_head: int, block_size: int):
        self.ln1 = LayerNorm(d_model)
        self.attn = CausalSelfAttention(d_model, n_head, block_size)
        self.ln2 = LayerNorm(d_model)
        self.mlp = MLP(d_model)

    def __call__(self, x: Tensor, capture_attn: bool = False) -> Tensor:
        x = x + self.attn(self.ln1(x), capture_attn=capture_attn)
        x = x + self.mlp(self.ln2(x))
        return x

    def parameters(self):
        return (self.ln1.parameters() + self.attn.parameters() +
                self.ln2.parameters() + self.mlp.parameters())


class GPT:
    def __init__(self, vocab_size: int, d_model: int, n_layer: int, n_head: int, block_size: int):
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.n_layer = n_layer
        self.n_head = n_head
        self.block_size = block_size

        self.wte = _param((vocab_size, d_model), scale=0.02)
        self.wpe = _param((block_size, d_model), scale=0.02)
        self.blocks = [Block(d_model, n_head, block_size) for _ in range(n_layer)]
        self.ln_f = LayerNorm(d_model)
        self.head = Linear(d_model, vocab_size, bias=False)

    def __call__(self, idx: np.ndarray, capture_attn: bool = False) -> Tensor:
        B, T = idx.shape
        if T > self.block_size:
            raise ValueError(f"sequence length {T} exceeds block_size {self.block_size}")
        tok_emb = embedding(self.wte, idx)               # (B, T, d)
        pos_emb = embedding(self.wpe, np.arange(T))       # (T, d)
        x = tok_emb + pos_emb
        for block in self.blocks:
            x = block(x, capture_attn=capture_attn)
        x = self.ln_f(x)
        return self.head(x)                               # (B, T, vocab)

    def attention_maps(self):
        """Attention weight snapshots captured on the last forward() call
        with capture_attn=True, one (B, n_head, T, T) array per layer."""
        return [block.attn.last_attn for block in self.blocks]

    def parameters(self):
        ps = [self.wte, self.wpe]
        for block in self.blocks:
            ps += block.parameters()
        ps += self.ln_f.parameters() + self.head.parameters()
        return ps

    def num_params(self) -> int:
        return sum(p.data.size for p in self.parameters())

    def config(self) -> dict:
        return dict(vocab_size=self.vocab_size, d_model=self.d_model, n_layer=self.n_layer,
                    n_head=self.n_head, block_size=self.block_size)
