"""A brute-force truth oracle and exact model counter.

Used as an independent ground truth for differential testing of the CDCL solver,
and as the engine behind the #SAT / AllSAT feature for small instances.
"""

from __future__ import annotations

from typing import List, Optional, Iterator


def _clause_sat(clause: List[int], bits: int) -> bool:
    for lit in clause:
        v = abs(lit)
        val = (bits >> (v - 1)) & 1  # 1 == True
        if (val == 1 and lit > 0) or (val == 0 and lit < 0):
            return True
    return False


def brute_solve(num_vars: int, clauses: List[List[int]]) -> Optional[List[int]]:
    """Return a satisfying assignment (list of signed literals) or None if UNSAT.

    Exhaustive over 2**num_vars — only for small instances.
    """
    if num_vars > 24:
        raise ValueError("brute_solve is only intended for <= 24 variables")
    for bits in range(1 << num_vars):
        if all(_clause_sat(c, bits) for c in clauses):
            return [(v if (bits >> (v - 1)) & 1 else -v) for v in range(1, num_vars + 1)]
    return None


def brute_is_sat(num_vars: int, clauses: List[List[int]]) -> bool:
    return brute_solve(num_vars, clauses) is not None


def count_models(num_vars: int, clauses: List[List[int]]) -> int:
    """Exact #SAT: number of full assignments satisfying every clause."""
    if num_vars > 24:
        raise ValueError("count_models is only intended for <= 24 variables")
    total = 0
    for bits in range(1 << num_vars):
        if all(_clause_sat(c, bits) for c in clauses):
            total += 1
    return total


def all_models(num_vars: int, clauses: List[List[int]]) -> Iterator[List[int]]:
    if num_vars > 24:
        raise ValueError("all_models is only intended for <= 24 variables")
    for bits in range(1 << num_vars):
        if all(_clause_sat(c, bits) for c in clauses):
            yield [(v if (bits >> (v - 1)) & 1 else -v) for v in range(1, num_vars + 1)]
