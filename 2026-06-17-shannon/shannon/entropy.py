"""Information-theoretic measurements used for analysis and as test oracles."""
from __future__ import annotations

import math
from collections import Counter
from typing import Dict


def symbol_counts(data: bytes) -> Counter:
    return Counter(data)


def order0_entropy(data: bytes) -> float:
    """Shannon entropy H0 in *bits per symbol* (order-0 / memoryless model)."""
    n = len(data)
    if n == 0:
        return 0.0
    counts = symbol_counts(data)
    h = 0.0
    for c in counts.values():
        p = c / n
        h -= p * math.log2(p)
    return h


def order1_entropy(data: bytes) -> float:
    """Conditional entropy H(X_i | X_{i-1}) in bits per symbol.

    Estimates how compressible the data is under an order-1 (previous-byte
    context) model — the bound the order-1 arithmetic coder targets.
    """
    n = len(data)
    if n <= 1:
        return order0_entropy(data)
    # joint counts of (prev, cur) and marginal of prev (over positions 0..n-2)
    pair: Dict[int, Counter] = {}
    prev_total: Counter = Counter()
    for i in range(1, n):
        p = data[i - 1]
        c = data[i]
        prev_total[p] += 1
        pair.setdefault(p, Counter())[c] += 1
    total_pairs = n - 1
    h = 0.0
    for p, ctx_counts in pair.items():
        ctx_n = prev_total[p]
        p_prev = ctx_n / total_pairs
        ctx_h = 0.0
        for c in ctx_counts.values():
            pc = c / ctx_n
            ctx_h -= pc * math.log2(pc)
        h += p_prev * ctx_h
    return h


def ideal_bytes(data: bytes, order: int = 0) -> float:
    """Theoretical minimum size in *bytes* under the given model order."""
    if order == 0:
        return order0_entropy(data) * len(data) / 8.0
    if order == 1:
        # cost of first symbol under order-0 plus the rest under order-1
        if not data:
            return 0.0
        return (order0_entropy(data[:1]) + order1_entropy(data) * (len(data) - 1)) / 8.0
    raise ValueError("order must be 0 or 1")
