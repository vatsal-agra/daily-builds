"""Autoregressive generation from a trained checkpoint: temperature, top-k,
and top-p (nucleus) sampling."""
import numpy as np


def _logits_to_probs(logits_row, temperature, top_k, top_p):
    logits_row = logits_row / max(temperature, 1e-6)
    if top_k is not None and top_k > 0:
        top_k = min(top_k, logits_row.shape[-1])
        kth = np.partition(logits_row, -top_k)[-top_k]
        logits_row = np.where(logits_row < kth, -np.inf, logits_row)

    shifted = logits_row - np.max(logits_row)
    probs = np.exp(shifted)
    probs /= probs.sum()

    if top_p is not None and 0 < top_p < 1.0:
        order = np.argsort(-probs)
        sorted_probs = probs[order]
        cumulative = np.cumsum(sorted_probs)
        cutoff = np.searchsorted(cumulative, top_p) + 1
        keep = order[:cutoff]
        mask = np.zeros_like(probs, dtype=bool)
        mask[keep] = True
        probs = np.where(mask, probs, 0.0)
        probs /= probs.sum()

    # Defensive final renormalization: chained float64 masking/division can
    # leave probs summing to e.g. 0.9999999998 rather than exactly 1.0,
    # which np.random.Generator.choice rejects outright.
    probs = probs / probs.sum()
    return probs


def generate(model, tokenizer, prompt, max_new_tokens=100, temperature=1.0, top_k=None, top_p=None,
             seed=None, capture_attn=False):
    """Returns (generated_text, trace) where trace is a list of per-step
    dicts (token id, token bytes, chosen probability, attention weights if
    capture_attn) -- real data from the actual forward passes, used by the
    HTML visualizer's generation replay."""
    rng = np.random.default_rng(seed)
    ids = tokenizer.encode(prompt) if prompt else []
    if not ids:
        ids = [rng.integers(0, tokenizer.vocab_size)]

    trace = []
    for _ in range(max_new_tokens):
        context = ids[-model.block_size:]
        x = np.array([context], dtype=np.int64)
        logits = model.forward(x, capture_attn=capture_attn)
        last_logits = logits.data[0, -1]
        probs = _logits_to_probs(last_logits, temperature, top_k, top_p)
        next_id = int(rng.choice(len(probs), p=probs))
        step_info = {
            "token_id": next_id,
            "token_str": tokenizer.decode([next_id]),
            "prob": float(probs[next_id]),
        }
        if capture_attn:
            # attention weights for the just-consumed context, one array per layer
            step_info["attn"] = [layer_att[0].tolist() for layer_att in model._last_attn]
            step_info["context_ids"] = list(context)
        trace.append(step_info)
        ids.append(next_id)

    text = tokenizer.decode(ids)
    return text, trace
