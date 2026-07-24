"""A GPT-2-style decoder-only transformer, built entirely from loom.engine
primitives. No PyTorch/TensorFlow/JAX -- every layer here is Tensor ops
whose gradients are the ones verified in tests/test_engine.py.
"""
import math
from dataclasses import dataclass

import numpy as np

from .engine import Tensor, layer_norm, embedding, dropout


@dataclass
class GPTConfig:
    vocab_size: int
    block_size: int = 128
    n_layer: int = 4
    n_head: int = 4
    n_embd: int = 128
    dropout: float = 0.1


def _param(*shape, scale=0.02):
    return Tensor(np.random.randn(*shape) * scale)


class Linear:
    def __init__(self, n_in, n_out, bias=True, scale=0.02):
        self.weight = _param(n_out, n_in, scale=scale)  # (out, in), GPT/PyTorch convention
        self.bias = Tensor(np.zeros(n_out)) if bias else None

    def __call__(self, x: Tensor) -> Tensor:
        out = x @ self.weight.transpose(0, 1)
        if self.bias is not None:
            out = out + self.bias
        return out

    def parameters(self):
        return [self.weight] + ([self.bias] if self.bias is not None else [])


class LayerNorm:
    def __init__(self, n):
        self.gamma = Tensor(np.ones(n))
        self.beta = Tensor(np.zeros(n))

    def __call__(self, x):
        return layer_norm(x, self.gamma, self.beta)

    def parameters(self):
        return [self.gamma, self.beta]


class CausalSelfAttention:
    def __init__(self, cfg: GPTConfig):
        assert cfg.n_embd % cfg.n_head == 0
        self.n_head = cfg.n_head
        self.head_dim = cfg.n_embd // cfg.n_head
        self.c_attn = Linear(cfg.n_embd, 3 * cfg.n_embd)
        self.c_proj = Linear(cfg.n_embd, cfg.n_embd, scale=0.02 / math.sqrt(2 * cfg.n_layer))
        self.dropout_p = cfg.dropout
        block = cfg.block_size
        # 0 where attention is allowed (j <= i), -1e9 where masked (j > i)
        mask = np.triu(np.ones((block, block)), k=1) * -1e9
        self.mask = mask

    def __call__(self, x: Tensor, training: bool) -> Tensor:
        B, T, C = x.shape
        qkv = self.c_attn(x)  # (B, T, 3C)
        q = qkv[:, :, 0:C]
        k = qkv[:, :, C:2 * C]
        v = qkv[:, :, 2 * C:3 * C]

        nh, hd = self.n_head, self.head_dim
        q = q.reshape(B, T, nh, hd).transpose(1, 2)  # (B, nh, T, hd)
        k = k.reshape(B, T, nh, hd).transpose(1, 2)
        v = v.reshape(B, T, nh, hd).transpose(1, 2)

        att = (q @ k.transpose(-2, -1)) * (1.0 / math.sqrt(hd))  # (B, nh, T, T)
        att = att + Tensor(self.mask[:T, :T], requires_grad=False)
        att = att.softmax(axis=-1)
        att = dropout(att, self.dropout_p, training)

        out = att @ v  # (B, nh, T, hd)
        out = out.transpose(1, 2).reshape(B, T, C)
        out = self.c_proj(out)
        out = dropout(out, self.dropout_p, training)
        return out

    def parameters(self):
        return self.c_attn.parameters() + self.c_proj.parameters()


class MLP:
    def __init__(self, cfg: GPTConfig):
        self.c_fc = Linear(cfg.n_embd, 4 * cfg.n_embd)
        self.c_proj = Linear(4 * cfg.n_embd, cfg.n_embd, scale=0.02 / math.sqrt(2 * cfg.n_layer))
        self.dropout_p = cfg.dropout

    def __call__(self, x: Tensor, training: bool) -> Tensor:
        x = self.c_fc(x)
        x = x.gelu()
        x = self.c_proj(x)
        x = dropout(x, self.dropout_p, training)
        return x

    def parameters(self):
        return self.c_fc.parameters() + self.c_proj.parameters()


class Block:
    def __init__(self, cfg: GPTConfig):
        self.ln1 = LayerNorm(cfg.n_embd)
        self.attn = CausalSelfAttention(cfg)
        self.ln2 = LayerNorm(cfg.n_embd)
        self.mlp = MLP(cfg)

    def __call__(self, x: Tensor, training: bool) -> Tensor:
        x = x + self.attn(self.ln1(x), training)
        x = x + self.mlp(self.ln2(x), training)
        return x

    def parameters(self):
        return self.ln1.parameters() + self.attn.parameters() + self.ln2.parameters() + self.mlp.parameters()


class GPT:
    def __init__(self, cfg: GPTConfig):
        self.cfg = cfg
        self.wte = _param(cfg.vocab_size, cfg.n_embd)
        self.wpe = _param(cfg.block_size, cfg.n_embd)
        self.blocks = [Block(cfg) for _ in range(cfg.n_layer)]
        self.ln_f = LayerNorm(cfg.n_embd)
        self.dropout_p = cfg.dropout

    def __call__(self, idx: np.ndarray, targets: np.ndarray = None, training: bool = True):
        B, T = idx.shape
        assert T <= self.cfg.block_size, f"sequence length {T} exceeds block_size {self.cfg.block_size}"

        tok_emb = embedding(self.wte, idx)          # (B, T, C)
        pos_emb = self.wpe[np.arange(T)]             # (T, C), broadcasts over B
        x = dropout(tok_emb + pos_emb, self.dropout_p, training)

        for block in self.blocks:
            x = block(x, training)
        x = self.ln_f(x)

        logits = x @ self.wte.transpose(0, 1)  # weight-tied LM head: (B, T, vocab)

        loss = None
        if targets is not None:
            from .engine import cross_entropy
            C = self.cfg.vocab_size
            loss = cross_entropy(logits.reshape(B * T, C), targets.reshape(-1))
        return logits, loss

    def parameters(self):
        params = [self.wte, self.wpe] + self.ln_f.parameters()
        for b in self.blocks:
            params += b.parameters()
        return params

    def num_params(self):
        return sum(p.data.size for p in self.parameters())
