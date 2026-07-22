"""Autoregressive sampling: temperature / top-k / top-p, with or without a KV-cache."""

import numpy as np


def _numpy_softmax(x):
    x = x - x.max()
    e = np.exp(x)
    return e / e.sum()


def sample_from_logits(logits_row, rng, temperature=1.0, top_k=None, top_p=None):
    """Sample one token id from a single 1D logits vector."""
    logits_row = logits_row.astype(np.float64) / max(temperature, 1e-6)

    if top_k is not None and top_k < len(logits_row):
        threshold = np.partition(logits_row, -top_k)[-top_k]
        logits_row = np.where(logits_row < threshold, -np.inf, logits_row)

    probs = _numpy_softmax(logits_row)

    if top_p is not None and 0 < top_p < 1.0:
        order = np.argsort(-probs)
        sorted_probs = probs[order]
        cumulative = np.cumsum(sorted_probs)
        cutoff = int(np.searchsorted(cumulative, top_p) + 1)
        keep = order[:cutoff]
        mask = np.zeros_like(probs)
        mask[keep] = probs[keep]
        probs = mask / mask.sum()

    return int(rng.choice(len(probs), p=probs))


def generate(model, tokenizer, prompt, max_new_tokens, temperature=1.0, top_k=None, top_p=None,
             rng=None, use_cache=True):
    """Generate a continuation of ``prompt``. Returns (full_text, generated_ids)."""
    rng = rng if rng is not None else np.random.default_rng()
    prompt_ids = tokenizer.encode(prompt) if prompt else [ord("\n")]
    prompt_ids = [i for i in prompt_ids if i < tokenizer.vocab_size]
    if not prompt_ids:
        prompt_ids = [ord("\n")]

    generated = list(prompt_ids)

    if use_cache:
        cache = model.new_cache()
        pos = 0
        x = np.array([generated[-model.max_seq_len:]])
        logits, _ = model.forward(x, cache=cache, pos_offset=pos)
        pos = x.shape[1]
        next_logits = logits.data[0, -1]
        for _ in range(max_new_tokens):
            if pos >= model.max_seq_len:
                break
            next_id = sample_from_logits(next_logits, rng, temperature, top_k, top_p)
            generated.append(next_id)
            x = np.array([[next_id]])
            logits, _ = model.forward(x, cache=cache, pos_offset=pos)
            pos += 1
            next_logits = logits.data[0, -1]
    else:
        for _ in range(max_new_tokens):
            context = generated[-model.max_seq_len:]
            x = np.array([context])
            logits, _ = model.forward(x, cache=None, pos_offset=0)
            next_logits = logits.data[0, -1]
            next_id = sample_from_logits(next_logits, rng, temperature, top_k, top_p)
            generated.append(next_id)
            if len(generated) >= model.max_seq_len:
                break

    return tokenizer.decode(generated), generated


def attention_snapshot(model, tokenizer, text, max_len=None):
    """Run a single non-cached forward pass over ``text`` and return per-layer,
    per-head attention weight matrices for visualization, plus the token strings."""
    ids = tokenizer.encode(text)
    if max_len is not None:
        ids = ids[-max_len:]
    ids = ids[-model.max_seq_len:]
    x = np.array([ids])
    _, attn_maps = model.forward(x, cache=None)
    tokens = [tokenizer.decode([i]) for i in ids]
    # attn_maps[layer].data shape: (1, n_heads, T, T)
    layers = [layer.data[0] for layer in attn_maps]
    return tokens, layers
