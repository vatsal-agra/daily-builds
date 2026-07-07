"""Autoregressive sampling: greedy, temperature, top-k, top-p (nucleus)."""
import numpy as np

from .functional import softmax
from .tensor import Tensor, no_grad


def _logits_to_probs(logits_row, temperature, top_k, top_p, rng):
    logits_row = logits_row / max(temperature, 1e-6)

    if top_k is not None:
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")
        if top_k < len(logits_row):
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

    # Sampling never calls .backward(), so run the forward pass under
    # no_grad(): ops skip building _children/_backward entirely, which means
    # no reference cycle is created in the first place - the deeper fix,
    # rather than periodically gc.collect()-ing cycles after the fact.
    with no_grad():
        for _ in range(max_new_tokens):
            window = np.array(ids[-model.block_size:], dtype=np.int64).reshape(1, -1)
            logits = model(window)
            last_logits = logits.data[0, -1]

            if greedy:
                next_id = int(np.argmax(last_logits))
            else:
                probs = _logits_to_probs(last_logits, temperature, top_k, top_p, rng)
                next_id = int(rng.choice(len(probs), p=probs))
            ids.append(next_id)

    return tok.decode(ids)
