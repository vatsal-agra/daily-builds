"""Autoregressive sampling: greedy, temperature, top-k, top-p (nucleus)."""
import gc

import numpy as np

from .functional import softmax
from .tensor import Tensor


def _logits_to_probs(logits_row, temperature, top_k, top_p, rng):
    logits_row = logits_row / max(temperature, 1e-6)

    if top_k is not None and top_k < len(logits_row):
        kth = np.partition(logits_row, -top_k)[-top_k]
        logits_row = np.where(logits_row < kth, -np.inf, logits_row)

    probs = softmax(Tensor(logits_row.reshape(1, -1)), axis=-1).data[0]

    if top_p is not None and top_p < 1.0:
        order = np.argsort(-probs)
        sorted_probs = probs[order]
        cum = np.cumsum(sorted_probs)
        cutoff = np.searchsorted(cum, top_p) + 1
        keep = order[:cutoff]
        mask = np.zeros_like(probs, dtype=bool)
        mask[keep] = True
        probs = np.where(mask, probs, 0.0)
        probs = probs / probs.sum()

    return probs


def generate(model, tok, prompt, max_new_tokens=200, temperature=1.0,
             top_k=None, top_p=None, greedy=False, seed=None):
    rng = np.random.default_rng(seed)
    ids = tok.encode(prompt) if prompt else [rng.integers(0, tok.vocab_size)]
    ids = list(ids)

    for step in range(max_new_tokens):
        window = np.array(ids[-model.block_size:], dtype=np.int64).reshape(1, -1)
        logits = model(window)
        last_logits = logits.data[0, -1].copy()
        del logits

        if greedy:
            next_id = int(np.argmax(last_logits))
        else:
            probs = _logits_to_probs(last_logits, temperature, top_k, top_p, rng)
            next_id = int(rng.choice(len(probs), p=probs))
        ids.append(next_id)

        # Every Tensor op leaves behind a self-referential closure (a
        # reference cycle), so long generations need periodic explicit
        # collection to keep memory from growing unboundedly.
        if step % 20 == 0:
            gc.collect()

    return tok.decode(ids)
