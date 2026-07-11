"""GPT-style decoder-only Transformer, built entirely from loom.tensor ops.

Because every op in tensor.py owns a correct backward pass, the model's
backward pass (attention, MLP, layernorm, residual streams, all of it) falls
out for free from composition -- there is no model-specific backward code
here. That composability is exactly what's being tested; see
tests/test_nn.py for gradient checks on each module and on the full model.
"""
import numpy as np

from .tensor import Tensor, embedding


def _init_linear(fan_in, fan_out, rng):
    # scaled so pre-activations start at roughly unit variance
    limit = 1.0 / np.sqrt(fan_in)
    return rng.uniform(-limit, limit, size=(fan_in, fan_out))


class Linear:
    def __init__(self, in_dim, out_dim, rng, bias=True):
        self.weight = Tensor(_init_linear(in_dim, out_dim, rng), requires_grad=True)
        self.bias = Tensor(np.zeros(out_dim), requires_grad=True) if bias else None

    def __call__(self, x):
        out = x @ self.weight
        if self.bias is not None:
            out = out + self.bias
        return out

    def parameters(self):
        return [self.weight] + ([self.bias] if self.bias is not None else [])


class LayerNorm:
    def __init__(self, dim):
        self.gamma = Tensor(np.ones(dim), requires_grad=True)
        self.beta = Tensor(np.zeros(dim), requires_grad=True)

    def __call__(self, x):
        return x.layernorm(self.gamma, self.beta)

    def parameters(self):
        return [self.gamma, self.beta]


class Embedding:
    def __init__(self, num, dim, rng, scale=0.02):
        self.weight = Tensor(rng.normal(0, scale, size=(num, dim)), requires_grad=True)

    def __call__(self, idx):
        return embedding(self.weight, idx)

    def parameters(self):
        return [self.weight]


_CAUSAL_MASK_CACHE = {}


def _causal_mask(T):
    if T not in _CAUSAL_MASK_CACHE:
        _CAUSAL_MASK_CACHE[T] = np.triu(np.ones((T, T), dtype=bool), k=1)
    return _CAUSAL_MASK_CACHE[T]


class CausalSelfAttention:
    def __init__(self, n_embd, n_head, rng):
        assert n_embd % n_head == 0
        self.n_head = n_head
        self.head_dim = n_embd // n_head
        self.qkv = Linear(n_embd, 3 * n_embd, rng)
        self.proj = Linear(n_embd, n_embd, rng)

    def __call__(self, x):
        B, T, C = x.shape
        nh, hs = self.n_head, self.head_dim
        qkv = self.qkv(x)  # (B, T, 3C)
        q = qkv[:, :, 0:C]
        k = qkv[:, :, C:2 * C]
        v = qkv[:, :, 2 * C:3 * C]

        # (B, T, C) -> (B, nh, T, hs)
        q = q.reshape(B, T, nh, hs).transpose(0, 2, 1, 3)
        k = k.reshape(B, T, nh, hs).transpose(0, 2, 1, 3)
        v = v.reshape(B, T, nh, hs).transpose(0, 2, 1, 3)

        att = (q @ k.swapaxes(-2, -1)) * (1.0 / np.sqrt(hs))  # (B, nh, T, T)
        att = att.masked_fill(_causal_mask(T), -1e9)
        att = att.softmax(axis=-1)
        out = att @ v  # (B, nh, T, hs)

        out = out.transpose(0, 2, 1, 3).reshape(B, T, C)
        return self.proj(out)

    def parameters(self):
        return self.qkv.parameters() + self.proj.parameters()


class MLP:
    def __init__(self, n_embd, rng, mult=4):
        self.fc1 = Linear(n_embd, mult * n_embd, rng)
        self.fc2 = Linear(mult * n_embd, n_embd, rng)

    def __call__(self, x):
        return self.fc2(self.fc1(x).gelu())

    def parameters(self):
        return self.fc1.parameters() + self.fc2.parameters()


class Block:
    def __init__(self, n_embd, n_head, rng):
        self.ln1 = LayerNorm(n_embd)
        self.attn = CausalSelfAttention(n_embd, n_head, rng)
        self.ln2 = LayerNorm(n_embd)
        self.mlp = MLP(n_embd, rng)

    def __call__(self, x):
        x = x + self.attn(self.ln1(x))
        x = x + self.mlp(self.ln2(x))
        return x

    def parameters(self):
        return self.ln1.parameters() + self.attn.parameters() + self.ln2.parameters() + self.mlp.parameters()


class GPT:
    """Decoder-only Transformer. Output head is weight-tied to the token
    embedding (GPT-2 style): logits = ln_f(x) @ tok_emb.weight.T"""

    def __init__(self, vocab_size, block_size, n_embd=64, n_head=4, n_layer=2, seed=0):
        rng = np.random.default_rng(seed)
        self.vocab_size = vocab_size
        self.block_size = block_size
        self.n_embd = n_embd
        self.n_head = n_head
        self.n_layer = n_layer

        self.tok_emb = Embedding(vocab_size, n_embd, rng)
        self.pos_emb = Tensor(rng.normal(0, 0.02, size=(block_size, n_embd)), requires_grad=True)
        self.blocks = [Block(n_embd, n_head, rng) for _ in range(n_layer)]
        self.ln_f = LayerNorm(n_embd)
        self._last_attn = None  # populated on request for the visualizer

    def parameters(self):
        params = self.tok_emb.parameters() + [self.pos_emb] + self.ln_f.parameters()
        for b in self.blocks:
            params += b.parameters()
        return params

    def forward(self, idx, capture_attn=False):
        """idx: numpy int array (B, T) with T <= block_size.
        Returns logits Tensor (B, T, vocab_size)."""
        B, T = idx.shape
        assert T <= self.block_size, f"sequence length {T} exceeds block_size {self.block_size}"
        x = self.tok_emb(idx) + self.pos_emb[0:T]
        if capture_attn:
            self._last_attn = []
            for blk in self.blocks:
                x, att = self._block_with_attn(blk, x)
                self._last_attn.append(att)
        else:
            for blk in self.blocks:
                x = blk(x)
        x = self.ln_f(x)
        logits = x @ self.tok_emb.weight.transpose(1, 0)
        return logits

    def _block_with_attn(self, blk, x):
        """Same math as Block.__call__ but also returns the attention
        weights (as a plain numpy array, detached) for visualization."""
        ln1 = blk.ln1(x)
        B, T, C = ln1.shape
        nh, hs = blk.attn.n_head, blk.attn.head_dim
        qkv = blk.attn.qkv(ln1)
        q = qkv[:, :, 0:C].reshape(B, T, nh, hs).transpose(0, 2, 1, 3)
        k = qkv[:, :, C:2 * C].reshape(B, T, nh, hs).transpose(0, 2, 1, 3)
        v = qkv[:, :, 2 * C:3 * C].reshape(B, T, nh, hs).transpose(0, 2, 1, 3)
        att_t = (q @ k.swapaxes(-2, -1)) * (1.0 / np.sqrt(hs))
        att_t = att_t.masked_fill(_causal_mask(T), -1e9)
        att_t = att_t.softmax(axis=-1)
        att_weights = att_t.data.copy()  # (B, nh, T, T)
        out = att_t @ v
        out = out.transpose(0, 2, 1, 3).reshape(B, T, C)
        attn_out = blk.attn.proj(out)
        x = x + attn_out
        x = x + blk.mlp(blk.ln2(x))
        return x, att_weights

    def __call__(self, idx, targets=None, capture_attn=False):
        logits = self.forward(idx, capture_attn=capture_attn)
        if targets is None:
            return logits, None
        loss = logits.cross_entropy(targets)
        return logits, loss
