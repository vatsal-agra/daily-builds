"""
Autoregressive sampling: temperature / top-k / top-p (nucleus), plus a
KV-cached fast path. Both paths must produce identical token streams for
the same seed (checked in tests/test_generate.py) — the cache is a pure
performance optimization, not a different model.

KV-cache scope: generation is limited to `n_ctx` total tokens (prompt +
generated). The naive path instead slides a length-`n_ctx` window and
keeps generating indefinitely — exactly how the model was trained (on
random length-`n_ctx` crops of the corpus, always at positions 0..n_ctx-1
relative to the crop start), so re-zeroing position on each slide is not
an approximation, it's what the model actually learned. The cache path
does not support this (positions only ever increase), so it is capped —
attempting to exceed n_ctx raises rather than silently corrupting output.
"""
import numpy as np

from .tensor_ops import softmax


def sample_from_logits(logits, temperature, top_k, top_p, rng):
    """logits: (B, V) -> (B,) sampled token ids."""
    logits = logits.astype(np.float64) / max(temperature, 1e-6)
    logits = logits.copy()
    B, V = logits.shape

    if top_k is not None and 0 < top_k < V:
        order = np.argsort(-logits, axis=-1)
        for b in range(B):
            logits[b, order[b, top_k:]] = -1e10

    probs = softmax(logits, axis=-1)

    if top_p is not None and 0 < top_p < 1.0:
        for b in range(B):
            order = np.argsort(-probs[b])
            sorted_probs = probs[b, order]
            cum = np.cumsum(sorted_probs)
            cutoff = int(np.searchsorted(cum, top_p) + 1)
            keep = order[:cutoff]
            mask = np.ones(V, dtype=bool)
            mask[keep] = False
            probs[b, mask] = 0.0
            s = probs[b].sum()
            probs[b] = probs[b] / s if s > 0 else np.eye(V)[order[0]]

    out = np.empty(B, dtype=np.int64)
    for b in range(B):
        out[b] = rng.choice(V, p=probs[b])
    return out


def generate_naive(model, idx, max_new_tokens, n_ctx, temperature=1.0, top_k=None,
                    top_p=None, rng=None, stop_token=None):
    rng = rng or np.random.default_rng()
    idx = idx.copy()
    for _ in range(max_new_tokens):
        idx_cond = idx[:, -n_ctx:]
        logits = model.forward(idx_cond)
        next_id = sample_from_logits(logits[:, -1, :], temperature, top_k, top_p, rng)
        idx = np.concatenate([idx, next_id.reshape(-1, 1)], axis=1)
        if stop_token is not None and idx.shape[0] == 1 and int(next_id[0]) == stop_token:
            break
    return idx


def generate_cached(model, idx, max_new_tokens, n_ctx, temperature=1.0, top_k=None,
                     top_p=None, rng=None, stop_token=None):
    rng = rng or np.random.default_rng()
    B, prompt_len = idx.shape
    if prompt_len + max_new_tokens > n_ctx:
        raise ValueError(
            f"KV-cache generation is capped at n_ctx={n_ctx} total tokens "
            f"(prompt {prompt_len} + requested {max_new_tokens} exceeds it); "
            f"use generate_naive for unbounded sliding-window generation."
        )
    caches = model.init_kv_caches()
    out = idx.copy()
    logits = None
    for pos in range(prompt_len):
        logits, caches = model.forward_step(idx[:, pos:pos + 1], pos, caches)
    cur_len = prompt_len
    for _ in range(max_new_tokens):
        next_id = sample_from_logits(logits[:, -1, :], temperature, top_k, top_p, rng)
        out = np.concatenate([out, next_id.reshape(-1, 1)], axis=1)
        if stop_token is not None and B == 1 and int(next_id[0]) == stop_token:
            break
        if cur_len >= n_ctx:
            break
        logits, caches = model.forward_step(next_id.reshape(-1, 1), cur_len, caches)
        cur_len += 1
    return out


def generate_text(model, tokenizer, prompt, n_ctx, max_new_tokens=200, temperature=0.9,
                   top_k=40, top_p=0.95, seed=0, use_cache=False, stop_at_eot=True):
    from .tokenizer import EOT_ID

    rng = np.random.default_rng(seed)
    prompt_ids = tokenizer.encode(prompt) if prompt else [EOT_ID]
    idx = np.array([prompt_ids], dtype=np.int64)
    stop_token = EOT_ID if stop_at_eot else None
    fn = generate_cached if use_cache else generate_naive
    out = fn(model, idx, max_new_tokens, n_ctx, temperature=temperature, top_k=top_k,
              top_p=top_p, rng=rng, stop_token=stop_token)
    new_ids = [t for t in out[0, len(prompt_ids):].tolist() if t != EOT_ID]
    return tokenizer.decode(new_ids)
