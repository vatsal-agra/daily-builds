"""Neural-network layers built as compositions of Tensor ops.

Every layer's backward pass is entirely engine-derived (autograd), not
hand-written - this file only defines forward composition + parameter
storage/initialization.
"""
import numpy as np

from .tensor import Tensor
from . import functional as F


class Module:
    def parameters(self):
        # Derived from _named_params() rather than re-implementing the same
        # __dict__ tree-walk a second time - the two used to be independent
        # copies, which meant a new submodule container type only had to be
        # taught to one of them to silently desync what the optimizer trains
        # from what state_dict()/load_state_dict() save and restore.
        return [t for _, t in self._named_params()]

    def zero_grad(self):
        for p in self.parameters():
            p.zero_grad()

    def state_dict(self):
        return {name: t.data.copy() for name, t in self._named_params()}

    def load_state_dict(self, state):
        named = self._named_params()
        missing = [name for name, _ in named if name not in state]
        if missing:
            raise KeyError(f"checkpoint is missing parameter(s): {missing}")
        for name, t in named:
            arr = state[name]
            if arr.shape != t.data.shape:
                raise ValueError(
                    f"shape mismatch for {name!r}: checkpoint has {arr.shape}, "
                    f"model expects {t.data.shape} (config.json and weights.npz "
                    "likely came from different runs)")
            t.data = arr.copy()

    def _named_params(self, prefix=""):
        out = []
        for k, v in self.__dict__.items():
            name = f"{prefix}{k}"
            if isinstance(v, Tensor) and v.requires_grad:
                out.append((name, v))
            elif isinstance(v, Module):
                out.extend(v._named_params(prefix=name + "."))
            elif isinstance(v, (list, tuple)):
                for i, item in enumerate(v):
                    if isinstance(item, Module):
                        out.extend(item._named_params(prefix=f"{name}.{i}."))
        return out


class Linear(Module):
    def __init__(self, n_in, n_out, rng, bias=True):
        scale = np.sqrt(2.0 / (n_in + n_out))
        self.weight = Tensor(rng.normal(0, scale, size=(n_in, n_out)), requires_grad=True)
        self.bias = Tensor(np.zeros(n_out), requires_grad=True) if bias else None

    def __call__(self, x):
        out = x @ self.weight
        if self.bias is not None:
            out = out + self.bias
        return out


class Embedding(Module):
    def __init__(self, n_vocab, n_dim, rng):
        self.weight = Tensor(rng.normal(0, 0.02, size=(n_vocab, n_dim)), requires_grad=True)

    def __call__(self, idx):
        # idx: numpy int array of any shape -> gather rows
        return self.weight[idx]


class LayerNorm(Module):
    def __init__(self, n_dim):
        self.gamma = Tensor(np.ones(n_dim), requires_grad=True)
        self.beta = Tensor(np.zeros(n_dim), requires_grad=True)

    def __call__(self, x):
        return F.layer_norm(x, self.gamma, self.beta)


class MultiHeadAttention(Module):
    def __init__(self, n_embd, n_head, rng):
        assert n_embd % n_head == 0
        self.n_head = n_head
        self.head_dim = n_embd // n_head
        self.q_proj = Linear(n_embd, n_embd, rng)
        self.k_proj = Linear(n_embd, n_embd, rng)
        self.v_proj = Linear(n_embd, n_embd, rng)
        self.out_proj = Linear(n_embd, n_embd, rng)

    def _split_heads(self, x, B, T):
        # (B,T,C) -> (B,n_head,T,head_dim)
        x = x.reshape(B, T, self.n_head, self.head_dim)
        return x.transpose(0, 2, 1, 3)

    def __call__(self, x, mask):
        B, T, C = x.shape
        q = self._split_heads(self.q_proj(x), B, T)
        k = self._split_heads(self.k_proj(x), B, T)
        v = self._split_heads(self.v_proj(x), B, T)

        scale = 1.0 / np.sqrt(self.head_dim)
        att = (q @ k.transpose(0, 1, 3, 2)) * scale  # (B,nh,T,T)
        att = att + mask  # broadcast (T,T) causal mask, additive -inf
        att = F.softmax(att, axis=-1)
        self.last_attn = att.data  # cached for visualization only, not used in the graph
        out = att @ v  # (B,nh,T,head_dim)

        out = out.transpose(0, 2, 1, 3).reshape(B, T, C)
        return self.out_proj(out)


class MLP(Module):
    def __init__(self, n_embd, rng, expansion=4):
        self.fc1 = Linear(n_embd, n_embd * expansion, rng)
        self.fc2 = Linear(n_embd * expansion, n_embd, rng)

    def __call__(self, x):
        return self.fc2(F.gelu(self.fc1(x)))


class TransformerBlock(Module):
    def __init__(self, n_embd, n_head, rng):
        self.ln1 = LayerNorm(n_embd)
        self.attn = MultiHeadAttention(n_embd, n_head, rng)
        self.ln2 = LayerNorm(n_embd)
        self.mlp = MLP(n_embd, rng)

    def __call__(self, x, mask):
        x = x + self.attn(self.ln1(x), mask)
        x = x + self.mlp(self.ln2(x))
        return x


class GPT(Module):
    """A decoder-only Transformer language model, GPT-style."""

    def __init__(self, vocab_size, n_embd=128, n_head=4, n_layer=4, block_size=128, seed=0):
        rng = np.random.default_rng(seed)
        self.vocab_size = vocab_size
        self.block_size = block_size
        self.n_embd = n_embd
        self.tok_emb = Embedding(vocab_size, n_embd, rng)
        self.pos_emb = Tensor(rng.normal(0, 0.02, size=(block_size, n_embd)), requires_grad=True)
        self.blocks = [TransformerBlock(n_embd, n_head, rng) for _ in range(n_layer)]
        self.ln_f = LayerNorm(n_embd)
        # weight-tied output head: reuse tok_emb.weight instead of a fresh matrix

    def __call__(self, idx):
        """idx: int array (B,T) with T <= block_size. Returns logits Tensor (B,T,vocab_size)."""
        B, T = idx.shape
        assert T <= self.block_size, f"sequence length {T} exceeds block_size {self.block_size}"
        tok = self.tok_emb(idx)                    # (B,T,C)
        pos = self.pos_emb[:T].reshape(1, T, self.n_embd)
        x = tok + pos
        mask = F.causal_mask(T)
        for block in self.blocks:
            x = block(x, mask)
        x = self.ln_f(x)
        # weight tying: logits = x @ tok_emb.weight^T
        logits = x @ self.tok_emb.weight.transpose(1, 0)
        return logits
