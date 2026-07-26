"""Autoregressive sampling from a trained GPT, with temperature, top-k, and
top-p (nucleus) filtering implemented directly on the logit array -- not a
single call to a library sampler that hides the math.
"""
import numpy as np

from .model import GPT


def _filter_logits(logits, top_k=0, top_p=0.0):
    """logits: 1D float array over the vocabulary. Returns a filtered copy
    where excluded entries are set to -inf, so a subsequent softmax assigns
    them exactly zero probability."""
    logits = logits.copy()
    vocab = logits.shape[0]

    if top_k and 0 < top_k < vocab:
        kth = np.partition(logits, vocab - top_k)[vocab - top_k]
        logits[logits < kth] = -np.inf

    if top_p and 0.0 < top_p < 1.0:
        order = np.argsort(-logits)
        sorted_logits = logits[order]
        shifted = sorted_logits - np.max(sorted_logits)
        probs = np.exp(shifted)
        probs /= probs.sum()
        cumprobs = np.cumsum(probs)
        # keep the smallest prefix whose cumulative probability >= top_p;
        # always keep at least one token.
        cutoff = np.searchsorted(cumprobs, top_p) + 1
        cutoff = max(1, min(cutoff, vocab))
        keep = order[:cutoff]
        mask = np.full(vocab, True)
        mask[keep] = False
        logits[mask] = -np.inf

    return logits


def sample_next_token(logits_1d, temperature=1.0, top_k=0, top_p=0.0, rng=None):
    rng = rng or np.random
    if temperature <= 0.0:
        return int(np.argmax(logits_1d))
    logits = logits_1d / temperature
    logits = _filter_logits(logits, top_k=top_k, top_p=top_p)
    shifted = logits - np.max(logits)
    probs = np.exp(shifted)
    probs /= probs.sum()
    return int(rng.choice(len(probs), p=probs))


def generate(model: GPT, prompt_ids, max_new_tokens=200, temperature=0.8,
             top_k=40, top_p=0.0, seed=None):
    """Yields (token_id, logits_1d) pairs one at a time so callers (CLI,
    server) can stream output and/or inspect attention for the same forward
    pass if needed."""
    rng = np.random.RandomState(seed) if seed is not None else np.random
    ids = list(prompt_ids)
    block_size = model.cfg.block_size
    for _ in range(max_new_tokens):
        window = ids[-block_size:]
        idx = np.array([window])
        logits, _ = model(idx, targets=None, training=False)
        last_logits = logits.data[0, -1, :]
        next_id = sample_next_token(last_logits, temperature, top_k, top_p, rng)
        ids.append(next_id)
        yield next_id, last_logits
    return


def generate_text(model, tokenizer, prompt, max_new_tokens=200, temperature=0.8,
                   top_k=40, top_p=0.0, seed=None):
    prompt_ids = tokenizer.encode(prompt) if prompt else [ord(" ")]
    if not prompt_ids:
        prompt_ids = [ord(" ")]
    out_ids = list(prompt_ids)
    for tok_id, _ in generate(model, prompt_ids, max_new_tokens, temperature, top_k, top_p, seed):
        out_ids.append(tok_id)
    return tokenizer.decode(out_ids)


def attention_weights(model: GPT, ids):
    """Runs a forward pass and returns the per-layer, per-head attention
    matrices actually produced by the model (not recomputed/approximated),
    by lightly instrumenting each block's attention call for this one pass."""
    import numpy as np
    from .engine import Tensor, dropout

    recorded = []
    idx = np.array([ids])
    B, T = idx.shape

    from .engine import embedding
    tok_emb = embedding(model.wte, idx)
    pos_emb = model.wpe[np.arange(T)]
    x = tok_emb + pos_emb

    for block in model.blocks:
        ln1_out = block.ln1(x)
        attn = block.attn
        C = model.cfg.n_embd
        qkv = attn.c_attn(ln1_out)
        q = qkv[:, :, 0:C]
        k = qkv[:, :, C:2 * C]
        v = qkv[:, :, 2 * C:3 * C]
        nh, hd = attn.n_head, attn.head_dim
        q = q.reshape(B, T, nh, hd).transpose(1, 2)
        k = k.reshape(B, T, nh, hd).transpose(1, 2)
        v = v.reshape(B, T, nh, hd).transpose(1, 2)
        att = (q @ k.transpose(-2, -1)) * (1.0 / (hd ** 0.5))
        att = att + Tensor(attn.mask[:T, :T], requires_grad=False)
        att = att.softmax(axis=-1)
        recorded.append(att.data[0])  # (nh, T, T)

        out = (att @ v).transpose(1, 2).reshape(B, T, C)
        out = attn.c_proj(out)
        x = x + out
        x = x + block.mlp(block.ln2(x), training=False)

    return recorded  # list of (n_head, T, T) arrays, one per layer
