"""
A GPT-style decoder-only Transformer, built entirely out of `Tensor` ops
from tensor.py. There is no other math library involved: attention,
layer norm, and the MLP are all composed from primitives whose backward
passes were already gradient-checked, so the model's backward pass is
correct "for free" as long as the composition is correct -- the one place
that isn't automatic is `CausalSelfAttention`, which is checked directly
in `loom.py gradcheck --model`.
"""
import numpy as np

from .tensor import Tensor, gelu


class Module:
    def parameters(self):
        params = []
        for v in vars(self).values():
            if isinstance(v, Tensor) and v.requires_grad:
                params.append(v)
            elif isinstance(v, Module):
                params.extend(v.parameters())
            elif isinstance(v, (list, tuple)):
                for item in v:
                    if isinstance(item, Module):
                        params.extend(item.parameters())
        return params

    def zero_grad(self):
        for p in self.parameters():
            p.grad = np.zeros_like(p.data)

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)


class Linear(Module):
    def __init__(self, in_features, out_features, bias=True, rng=None):
        rng = rng if rng is not None else np.random
        scale = 1.0 / np.sqrt(in_features)
        self.weight = Tensor(rng.uniform(-scale, scale, (in_features, out_features)), requires_grad=True)
        self.bias = Tensor(np.zeros(out_features), requires_grad=True) if bias else None

    def forward(self, x):
        out = x @ self.weight
        if self.bias is not None:
            out = out + self.bias
        return out


class Embedding(Module):
    def __init__(self, num_embeddings, dim, rng=None, std=0.02):
        rng = rng if rng is not None else np.random
        self.weight = Tensor(rng.normal(0.0, std, (num_embeddings, dim)), requires_grad=True)

    def forward(self, idx):
        return self.weight[np.asarray(idx)]


class LayerNorm(Module):
    def __init__(self, dim, eps=1e-5):
        self.gamma = Tensor(np.ones(dim), requires_grad=True)
        self.beta = Tensor(np.zeros(dim), requires_grad=True)
        self.eps = eps

    def forward(self, x):
        mean = x.mean(axis=-1, keepdims=True)
        centered = x - mean
        var = (centered ** 2).mean(axis=-1, keepdims=True)
        xhat = centered / (var + self.eps).sqrt()
        return xhat * self.gamma + self.beta


class MLP(Module):
    def __init__(self, dim, hidden_mult=4, rng=None):
        self.fc1 = Linear(dim, dim * hidden_mult, rng=rng)
        self.fc2 = Linear(dim * hidden_mult, dim, rng=rng)

    def forward(self, x):
        return self.fc2(gelu(self.fc1(x)))


class CausalSelfAttention(Module):
    def __init__(self, dim, n_head, max_len, rng=None):
        assert dim % n_head == 0, "dim must be divisible by n_head"
        self.dim = dim
        self.n_head = n_head
        self.head_dim = dim // n_head
        self.qkv = Linear(dim, 3 * dim, rng=rng)
        self.proj = Linear(dim, dim, rng=rng)
        # True where attention must NOT look (future positions). Plain
        # numpy array, not a Tensor -- it's a fixed structural constant,
        # not a learned or differentiated quantity.
        self.causal_mask = np.triu(np.ones((max_len, max_len), dtype=bool), k=1)
        self.last_attn = None  # (B, n_head, T, T) post-softmax weights of the last forward, for viz

    def _split_heads(self, t, B, T):
        return t.reshape(B, T, self.n_head, self.head_dim).transpose(0, 2, 1, 3)

    def forward(self, x):
        B, T, C = x.shape
        qkv = self.qkv(x)  # (B, T, 3C)
        q = qkv[:, :, 0:C]
        k = qkv[:, :, C:2 * C]
        v = qkv[:, :, 2 * C:3 * C]
        q = self._split_heads(q, B, T)  # (B, nh, T, hs)
        k = self._split_heads(k, B, T)
        v = self._split_heads(v, B, T)

        scale = 1.0 / np.sqrt(self.head_dim)
        att = (q @ k.transpose(0, 1, 3, 2)) * scale  # (B, nh, T, T)
        mask = self.causal_mask[:T, :T].reshape(1, 1, T, T)
        att = att.masked_fill(mask, -1e9)
        att = att.softmax(axis=-1)
        self.last_attn = att.data.copy()

        out = att @ v  # (B, nh, T, hs)
        out = out.transpose(0, 2, 1, 3).reshape(B, T, C)
        return self.proj(out)


class TransformerBlock(Module):
    def __init__(self, dim, n_head, max_len, rng=None):
        self.ln1 = LayerNorm(dim)
        self.attn = CausalSelfAttention(dim, n_head, max_len, rng=rng)
        self.ln2 = LayerNorm(dim)
        self.mlp = MLP(dim, rng=rng)

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        x = x + self.mlp(self.ln2(x))
        return x


class GPT(Module):
    def __init__(self, vocab_size, dim, n_layer, n_head, max_len, seed=None):
        rng = np.random.RandomState(seed)
        self.vocab_size = vocab_size
        self.dim = dim
        self.n_layer = n_layer
        self.n_head = n_head
        self.max_len = max_len

        self.tok_emb = Embedding(vocab_size, dim, rng=rng)
        self.pos_emb = Tensor(rng.normal(0.0, 0.02, (max_len, dim)), requires_grad=True)
        self.blocks = [TransformerBlock(dim, n_head, max_len, rng=rng) for _ in range(n_layer)]
        self.ln_f = LayerNorm(dim)
        # Output head reuses tok_emb.weight (weight tying) -- both the
        # embedding lookup and the transposed matmul below write into the
        # same Tensor's .grad during backward(); see tensor.py's docstring
        # on graph reuse for why that's safe.

    def config(self):
        return dict(vocab_size=self.vocab_size, dim=self.dim, n_layer=self.n_layer,
                    n_head=self.n_head, max_len=self.max_len)

    def forward(self, idx):
        idx = np.asarray(idx)
        B, T = idx.shape
        assert T <= self.max_len, f"sequence length {T} exceeds max_len {self.max_len}"
        tok = self.tok_emb(idx)          # (B, T, C)
        pos = self.pos_emb[:T]           # (T, C), broadcasts over batch
        x = tok + pos
        for block in self.blocks:
            x = block(x)
        x = self.ln_f(x)
        logits = x @ self.tok_emb.weight.transpose(1, 0)  # (B, T, V), weight-tied
        return logits

    def attention_maps(self):
        """Attention weights captured during the most recent forward pass,
        one (n_head, T, T) array per layer (batch dim squeezed to index 0)."""
        return [block.attn.last_attn[0] for block in self.blocks]
