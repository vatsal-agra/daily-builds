"""
GPT: embedding -> N transformer blocks -> final LayerNorm -> tied output head.

The output projection is weight-tied to the token embedding (`wte`), exactly
as GPT-2 does: logits = ln_f(x) @ wte.T. backward() must therefore route
gradient into wte from *two* places (the embedding lookup and the tied head)
and sum them, which is the one subtlety beyond the individual layers.
"""
import numpy as np

from .layers import Block, Embedding, LayerNorm
from .tensor_ops import cross_entropy_from_logits


class GPTConfig:
    def __init__(self, vocab_size, n_ctx, n_embd, n_head, n_layer, n_hidden=None):
        self.vocab_size = vocab_size
        self.n_ctx = n_ctx
        self.n_embd = n_embd
        self.n_head = n_head
        self.n_layer = n_layer
        self.n_hidden = n_hidden or 4 * n_embd


class GPT:
    def __init__(self, config, seed=0):
        self.config = config
        rng = np.random.default_rng(seed)
        self.embed = Embedding(config.vocab_size, config.n_ctx, config.n_embd, rng)
        self.blocks = [
            Block(config.n_embd, config.n_head, config.n_ctx, config.n_hidden, rng)
            for _ in range(config.n_layer)
        ]
        self.ln_f = LayerNorm(config.n_embd)
        self.grads = {}
        self._cache = None

    # ------------------------------------------------------------- params
    def params(self):
        p = {}
        for k, v in self.embed.params().items():
            p[f"embed.{k}"] = v
        for i, block in enumerate(self.blocks):
            for k, v in block.params().items():
                p[f"blocks.{i}.{k}"] = v
        for k, v in self.ln_f.params().items():
            p[f"ln_f.{k}"] = v
        return p

    def named_modules(self):
        mods = [("embed", self.embed)]
        for i, b in enumerate(self.blocks):
            mods.append((f"blocks.{i}", b))
        mods.append(("ln_f", self.ln_f))
        return mods

    # ------------------------------------------------------------ forward
    def forward(self, idx):
        x = self.embed.forward(idx)
        for block in self.blocks:
            x = block.forward(x)
        xln = self.ln_f.forward(x)
        logits = xln @ self.embed.wte.T
        self._cache = xln
        return logits

    def backward(self, dlogits):
        xln = self._cache
        B, T, V = dlogits.shape
        C = xln.shape[-1]
        dxln = dlogits @ self.embed.wte
        dwte_head = dlogits.reshape(-1, V).T @ xln.reshape(-1, C)

        dx = self.ln_f.backward(dxln)
        for block in reversed(self.blocks):
            dx = block.backward(dx)
        self.embed.backward(dx)
        self.embed.grads["wte"] = self.embed.grads["wte"] + dwte_head

        self.grads = {}
        for k, v in self.embed.grads.items():
            self.grads[f"embed.{k}"] = v
        for i, block in enumerate(self.blocks):
            for k, v in block.grads.items():
                self.grads[f"blocks.{i}.{k}"] = v
        for k, v in self.ln_f.grads.items():
            self.grads[f"ln_f.{k}"] = v

    def loss(self, idx, targets, ignore_index=None):
        logits = self.forward(idx)
        B, T, V = logits.shape
        loss, dlogits = cross_entropy_from_logits(
            logits.reshape(-1, V), targets.reshape(-1), ignore_index=ignore_index
        )
        self.backward(dlogits.reshape(B, T, V))
        return loss, logits

    # ------------------------------------------------- incremental (KV cache)
    def init_kv_caches(self):
        # (None, None) rather than bare None: Block.forward dispatches on
        # "is a kv_cache argument present at all" (cache mode) vs. "is there
        # anything cached yet" (first step). A bare None would collapse
        # those into the same case and silently fall back to the no-cache
        # training path, which returns x instead of (x, new_cache).
        return [(None, None) for _ in self.blocks]

    def forward_step(self, idx_step, pos, caches):
        """idx_step: (B,1) token ids at absolute position `pos` (scalar int)."""
        tok = self.embed.wte[idx_step]
        posemb = self.embed.wpe[pos][None, None, :]
        x = tok + posemb
        new_caches = []
        for block, cache in zip(self.blocks, caches):
            x, new_cache = block.forward(x, kv_cache=cache)
            new_caches.append(new_cache)
        xln = self.ln_f.forward(x)
        logits = xln @ self.embed.wte.T
        return logits, new_caches

    # ------------------------------------------------------------- persist
    def state_dict(self):
        return {k: v.copy() for k, v in self.params().items()}

    def load_state_dict(self, state):
        params = self.params()
        for k, v in state.items():
            params[k][...] = v
