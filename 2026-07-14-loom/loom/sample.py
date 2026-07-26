"""Autoregressive sampling: temperature, top-k, and top-p (nucleus)."""
import numpy as np

from loom.nn import softmax


def filter_logits(logits, top_k=None, top_p=None):
    """logits: (V,) float array. Returns a copy with disallowed entries set to -inf."""
    logits = logits.copy()
    V = logits.shape[0]

    if top_k is not None and 0 < top_k < V:
        kth = np.partition(logits, V - top_k)[V - top_k]
        logits[logits < kth] = -np.inf

    if top_p is not None and 0.0 < top_p < 1.0:
        order = np.argsort(-logits)
        sorted_logits = logits[order]
        probs = softmax(sorted_logits)
        cum = np.cumsum(probs)
        # keep the smallest prefix whose cumulative prob >= top_p; always keep at least 1
        cutoff = np.searchsorted(cum, top_p) + 1
        cutoff = max(1, min(cutoff, V))
        keep = order[:cutoff]
        mask = np.full(V, -np.inf)
        mask[keep] = logits[keep]
        logits = mask

    return logits


def generate(model, tokenizer, prompt, max_new_tokens=200, temperature=1.0,
             top_k=None, top_p=None, seed=None, return_probs=False):
    if temperature < 0:
        raise ValueError("temperature must be >= 0")
    rng = np.random.RandomState(seed)

    ids = tokenizer.encode(prompt)
    if len(ids) == 0:
        # empty prompt: seed with token 0 so the model has something to condition on
        ids = [0]
    ids = list(ids)

    all_probs = [] if return_probs else None

    for _ in range(max_new_tokens):
        context = np.array([ids[-model.max_seq_len:]], dtype=np.int64)
        logits, probs_all = model.forward(context)
        last_logits = logits[0, -1].astype(np.float64)

        if temperature == 0.0:
            next_id = int(np.argmax(last_logits))
        else:
            scaled = last_logits / temperature
            filtered = filter_logits(scaled, top_k=top_k, top_p=top_p)
            probs = softmax(filtered)
            next_id = int(rng.choice(len(probs), p=probs))

        ids.append(next_id)
        if return_probs:
            all_probs.append(probs_all)

    text = tokenizer.decode(ids)
    if return_probs:
        return text, ids, all_probs
    return text, ids
