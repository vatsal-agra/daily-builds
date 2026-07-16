"""Autoregressive sampling: greedy, temperature, top-k, and top-p (nucleus).

No KV-cache -- the model is tiny enough that recomputing the full forward
pass at every step is fast, and it keeps the code honest and simple.
"""
from __future__ import annotations

import numpy as np

from loom.model import GPT


def _filter_logits(logits: np.ndarray, top_k: int | None, top_p: float | None) -> np.ndarray:
    logits = logits.copy()
    if top_k is not None and top_k > 0 and top_k < logits.shape[-1]:
        kth = np.partition(logits, -top_k)[-top_k]
        logits[logits < kth] = -np.inf
    if top_p is not None and 0.0 < top_p < 1.0:
        order = np.argsort(-logits)
        sorted_logits = logits[order]
        probs = np.exp(sorted_logits - sorted_logits.max())
        probs /= probs.sum()
        cumulative = np.cumsum(probs)
        cutoff = np.searchsorted(cumulative, top_p) + 1
        cutoff = max(1, cutoff)
        keep = order[:cutoff]
        mask = np.full_like(logits, -np.inf)
        mask[keep] = logits[keep]
        logits = mask
    return logits


def generate(model: GPT, prompt_ids: list[int], max_new_tokens: int, temperature: float = 1.0,
             top_k: int | None = None, top_p: float | None = None,
             rng: np.random.Generator | None = None) -> list[int]:
    if len(prompt_ids) == 0:
        raise ValueError("prompt_ids must be non-empty")
    rng = rng or np.random.default_rng()
    ids = list(prompt_ids)
    for _ in range(max_new_tokens):
        context = ids[-model.block_size:]
        x = np.array([context])
        logits = model(x)
        last = logits.data[0, -1]  # (vocab,)

        if temperature <= 1e-8:
            next_id = int(np.argmax(last))
        else:
            scaled = last / temperature
            scaled = _filter_logits(scaled, top_k, top_p)
            shifted = scaled - np.max(scaled)
            probs = np.exp(shifted)
            probs /= probs.sum()
            next_id = int(rng.choice(len(probs), p=probs))
        ids.append(next_id)
    return ids
