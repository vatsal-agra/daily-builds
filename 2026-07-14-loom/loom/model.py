"""GPT-style decoder-only transformer, wired from the primitives in nn.py.

Architecture: token_emb[id] + pos_emb[pos] -> N x [pre-norm attn + residual,
pre-norm feedforward + residual] -> final layer norm -> output head
(weight-tied to the token embedding, halving parameter count and matching
what real small LMs do).
"""
import numpy as np

from loom.nn import CausalSelfAttention, Embedding, FeedForward, LayerNorm, Parameter


class TransformerBlock:
    def __init__(self, d_model, n_heads, rng=None):
        self.ln1 = LayerNorm(d_model)
        self.attn = CausalSelfAttention(d_model, n_heads, rng=rng)
        self.ln2 = LayerNorm(d_model)
        self.ff = FeedForward(d_model, rng=rng)

    def forward(self, x):
        a_in = self.ln1.forward(x)
        a_out, probs = self.attn.forward(a_in)
        x1 = x + a_out

        f_in = self.ln2.forward(x1)
        f_out = self.ff.forward(f_in)
        x2 = x1 + f_out
        return x2, probs

    def backward(self, dy):
        # x2 = x1 + f_out  -> both branches receive dy directly
        df_in = self.ff.backward(dy)
        dx1_from_ff = self.ln2.backward(df_in)
        dx1 = dy + dx1_from_ff

        # x1 = x + a_out -> both branches receive dx1 directly
        da_in = self.attn.backward(dx1)
        dx_from_attn = self.ln1.backward(da_in)
        dx = dx1 + dx_from_attn
        return dx

    def parameters(self):
        return (
            self.ln1.parameters()
            + self.attn.parameters()
            + self.ln2.parameters()
            + self.ff.parameters()
        )


class TransformerLM:
    def __init__(self, vocab_size, d_model, n_heads, n_layers, max_seq_len, seed=0):
        rng = np.random.RandomState(seed)
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.n_heads = n_heads
        self.n_layers = n_layers
        self.max_seq_len = max_seq_len

        self.tok_emb = Embedding(vocab_size, d_model, rng=rng)
        self.pos_emb = Parameter(rng.randn(max_seq_len, d_model) * 0.01)
        self.blocks = [TransformerBlock(d_model, n_heads, rng=rng) for _ in range(n_layers)]
        self.ln_f = LayerNorm(d_model)

        self._T = None
        self._final_x = None

    def forward(self, ids):
        """ids: (B,T) int array. Returns (logits (B,T,V), attn_probs per layer)."""
        B, T = ids.shape
        if T > self.max_seq_len:
            raise ValueError(f"sequence length {T} exceeds max_seq_len {self.max_seq_len}")
        self._T = T

        x = self.tok_emb.forward(ids) + self.pos_emb.value[:T][None, :, :]

        probs_all = []
        for block in self.blocks:
            x, probs = block.forward(x)
            probs_all.append(probs)

        x = self.ln_f.forward(x)
        self._final_x = x
        logits = x @ self.tok_emb.W.value.T
        return logits, probs_all

    def backward(self, dlogits):
        final_x = self._final_x
        B, T, D = final_x.shape
        V = dlogits.shape[-1]

        # logits = final_x @ W^T (weight tying): two gradient paths into W.
        dx = dlogits @ self.tok_emb.W.value
        dW_head = dlogits.reshape(-1, V).T @ final_x.reshape(-1, D)
        self.tok_emb.W.grad += dW_head

        dx = self.ln_f.backward(dx)
        for block in reversed(self.blocks):
            dx = block.backward(dx)

        self.pos_emb.grad[:self._T] += dx.sum(axis=0)
        self.tok_emb.backward(dx)

    def parameters(self):
        params = [self.tok_emb.W, self.pos_emb]
        for block in self.blocks:
            params += block.parameters()
        params += self.ln_f.parameters()
        return params

    def zero_grad(self):
        for p in self.parameters():
            p.zero_grad()

    def config(self):
        return dict(
            vocab_size=self.vocab_size,
            d_model=self.d_model,
            n_heads=self.n_heads,
            n_layers=self.n_layers,
            max_seq_len=self.max_seq_len,
        )

    def state_dict(self):
        return {f"p{i}": p.value for i, p in enumerate(self.parameters())}

    def load_state_dict(self, state):
        for i, p in enumerate(self.parameters()):
            arr = state[f"p{i}"]
            if arr.shape != p.value.shape:
                raise ValueError(f"shape mismatch for parameter p{i}: {arr.shape} vs {p.value.shape}")
            p.value[...] = arr

    @classmethod
    def from_config(cls, config, seed=0):
        return cls(
            vocab_size=config["vocab_size"],
            d_model=config["d_model"],
            n_heads=config["n_heads"],
            n_layers=config["n_layers"],
            max_seq_len=config["max_seq_len"],
            seed=seed,
        )
