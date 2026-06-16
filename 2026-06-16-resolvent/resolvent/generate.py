"""Seeded random CNF generation (uniform random k-SAT)."""
from __future__ import annotations

import random
from typing import Optional

from .cnf import CNF


def random_ksat(
    nvars: int,
    nclauses: int,
    k: int = 3,
    seed: int = 0,
    rng: Optional[random.Random] = None,
) -> CNF:
    """Generate a uniform random k-SAT instance.

    Each clause has ``k`` distinct variables with independently random signs.
    Fully determined by ``seed`` (or a supplied ``rng``)."""
    if k > nvars:
        raise ValueError(f"k={k} cannot exceed nvars={nvars}")
    if nvars < 1 or nclauses < 0:
        raise ValueError("need nvars >= 1 and nclauses >= 0")
    r = rng if rng is not None else random.Random(seed)
    cnf = CNF(nvars)
    for _ in range(nclauses):
        vs = r.sample(range(1, nvars + 1), k)
        clause = [v if r.random() < 0.5 else -v for v in vs]
        cnf.add_clause(clause)
    return cnf


def random_at_ratio(nvars: int, ratio: float, k: int = 3, seed: int = 0) -> CNF:
    """Random k-SAT at a given clause/variable ratio (3-SAT phase transition ≈ 4.26)."""
    return random_ksat(nvars, round(nvars * ratio), k=k, seed=seed)
