"""Model layers built entirely on loom.tensor's autodiff engine."""
import math
import numpy as np
from .tensor import Tensor

NEG_INF = -1e9


def param(*shape, scale=None):
    if scale is None:
        scale = 1.0 / math.sqrt(shape[0]) if len(shape) > 0 else 1.0
    return Tensor(np.random.randn(*shape) * scale, requires_grad=True)


class Linear:
    def __init__(self, d_in, d_out, bias=True):
        self.W = param(d_in, d_out)
        self.b = param(d_out, scale=0.0) if bias else None

    def __call__(self, x):
        y = x.matmul(self.W)
        if self.b is not None:
            y = y + self.b
        return y

    def params(self):
        return [self.W] + ([self.b] if self.b is not None else [])


class Embedding:
    def __init__(self, n, d):
        self.W = param(n, d, scale=0.02)

    def __call__(self, idx):
        """idx: plain numpy int array of any shape (NOT a Tensor — indices
        aren't differentiable, only the embedding table is)."""
        idx = np.asarray(idx)
        flat = idx.reshape(-1)
        out = self.W[flat]
        return out.reshape(*idx.shape, self.W.data.shape[-1])

    def params(self):
        return [self.W]


class LayerNorm:
    def __init__(self, d):
        self.gamma = Tensor(np.ones(d), requires_grad=True)
        self.beta = Tensor(np.zeros(d), requires_grad=True)

    def __call__(self, x):
        return x.layernorm(self.gamma, self.beta)

    def params(self):
        return [self.gamma, self.beta]


def causal_mask(T):
    """(T,T) additive mask: 0 on/below diagonal, -inf above."""
    m = np.triu(np.ones((T, T)), k=1) * NEG_INF
    return Tensor(m)


def dropout(x, p, training):
    """Inverted dropout: zero each element with prob p and rescale survivors
    by 1/(1-p) so expected activation is unchanged. A no-op at eval time.
    Implemented as a plain multiply by a constant mask, so backprop through
    it falls straight out of Tensor.__mul__ -- no custom backward needed."""
    if not training or p <= 0:
        return x
    mask = (np.random.random(x.data.shape) > p).astype(np.float64) / (1.0 - p)
    return x * Tensor(mask)


class MultiHeadAttention:
    def __init__(self, d_model, n_heads):
        if d_model % n_heads != 0:
            raise ValueError(f"d_model ({d_model}) must be divisible by n_heads ({n_heads})")
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_head = d_model // n_heads
        self.q_proj = Linear(d_model, d_model)
        self.k_proj = Linear(d_model, d_model)
        self.v_proj = Linear(d_model, d_model)
        self.out_proj = Linear(d_model, d_model)

    def _split_heads(self, x, B, T):
        # (B,T,d_model) -> (B,H,T,d_head)
        x = x.reshape(B, T, self.n_heads, self.d_head)
        return x.permute(0, 2, 1, 3)

    def _merge_heads(self, x, B, T):
        # (B,H,T,d_head) -> (B,T,d_model)
        x = x.permute(0, 2, 1, 3)
        return x.reshape(B, T, self.d_model)

    def __call__(self, x, mask):
        B, T, _ = x.shape
        q = self._split_heads(self.q_proj(x), B, T)
        k = self._split_heads(self.k_proj(x), B, T)
        v = self._split_heads(self.v_proj(x), B, T)

        scale = 1.0 / math.sqrt(self.d_head)
        scores = q.matmul(k.transpose_last2()) * scale  # (B,H,T,T)
        scores = scores + mask  # broadcast (T,T) causal mask
        weights = scores.softmax(axis=-1)
        ctx = weights.matmul(v)  # (B,H,T,d_head)
        ctx = self._merge_heads(ctx, B, T)
        return self.out_proj(ctx), weights

    def params(self):
        ps = []
        for m in (self.q_proj, self.k_proj, self.v_proj, self.out_proj):
            ps += m.params()
        return ps


class FeedForward:
    def __init__(self, d_model, d_ff):
        self.fc1 = Linear(d_model, d_ff)
        self.fc2 = Linear(d_ff, d_model)

    def __call__(self, x):
        return self.fc2(self.fc1(x).gelu())

    def params(self):
        return self.fc1.params() + self.fc2.params()


class TransformerBlock:
    def __init__(self, d_model, n_heads, d_ff, dropout_p=0.0):
        self.ln1 = LayerNorm(d_model)
        self.attn = MultiHeadAttention(d_model, n_heads)
        self.ln2 = LayerNorm(d_model)
        self.ff = FeedForward(d_model, d_ff)
        self.dropout_p = dropout_p

    def __call__(self, x, mask, training=False):
        a, weights = self.attn(self.ln1(x), mask)
        x = x + dropout(a, self.dropout_p, training)
        x = x + dropout(self.ff(self.ln2(x)), self.dropout_p, training)
        return x, weights

    def params(self):
        return self.ln1.params() + self.attn.params() + self.ln2.params() + self.ff.params()


class GPT:
    def __init__(self, vocab_size, d_model, n_heads, n_layers, d_ff, max_seq_len, dropout_p=0.0):
        self.vocab_size = vocab_size
        self.max_seq_len = max_seq_len
        self.dropout_p = dropout_p
        self.tok_emb = Embedding(vocab_size, d_model)
        self.pos_emb = Embedding(max_seq_len, d_model)
        self.blocks = [TransformerBlock(d_model, n_heads, d_ff, dropout_p) for _ in range(n_layers)]
        self.ln_f = LayerNorm(d_model)
        self.head = Linear(d_model, vocab_size, bias=False)

    def __call__(self, idx, return_attn=False, training=False):
        B, T = idx.shape
        if T > self.max_seq_len:
            raise ValueError(f"sequence length {T} exceeds max_seq_len {self.max_seq_len}")
        tok = self.tok_emb(idx)
        pos_idx = np.arange(T)
        pos = self.pos_emb(pos_idx)
        x = dropout(tok + pos, self.dropout_p, training)
        mask = causal_mask(T)
        attn_maps = []
        for block in self.blocks:
            x, w = block(x, mask, training=training)
            if return_attn:
                attn_maps.append(w.data)
        x = self.ln_f(x)
        logits = self.head(x)
        if return_attn:
            return logits, attn_maps
        return logits

    def params(self):
        ps = self.tok_emb.params() + self.pos_emb.params()
        for b in self.blocks:
            ps += b.params()
        ps += self.ln_f.params() + self.head.params()
        return ps

    def num_params(self):
        return sum(p.data.size for p in self.params())


def cross_entropy_loss(logits, targets):
    """logits: Tensor (B,T,V). targets: int array (B,T). Returns scalar Tensor.

    The true-class probability at each position is picked out via a one-hot
    dot product rather than fancy indexing, so the whole computation (softmax
    included) stays inside the autodiff graph and gets real gradients.
    """
    B, T, V = logits.shape
    flat_logits = logits.reshape(B * T, V)
    probs = flat_logits.softmax(axis=-1)
    flat_targets = targets.reshape(-1)
    onehot = np.zeros((B * T, V))
    onehot[np.arange(B * T), flat_targets] = 1.0
    true_prob = (probs * Tensor(onehot)).sum(axis=-1)
    nll = -true_prob.log()
    return nll.mean()
