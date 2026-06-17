"""A brute-force truth-table oracle for small formulas — the ground truth that
the CDCL solver is differentially tested against."""
from __future__ import annotations

from typing import List, Optional, Tuple

from .cnf import CNF


def brute_force(cnf: CNF, var_limit: int = 22) -> Tuple[bool, Optional[List[int]]]:
    """Decide ``cnf`` by exhaustive search. Returns ``(sat, model_or_None)``.

    Raises ``ValueError`` if ``nvars`` exceeds ``var_limit`` (the oracle is only
    meant for small instances)."""
    n = cnf.nvars
    if n > var_limit:
        raise ValueError(f"brute force refuses {n} > {var_limit} variables")
    if any(len(c) == 0 for c in cnf.clauses):
        return False, None
    # Precompute clauses as (var, sign) for speed.
    clauses = [[(abs(l), l > 0) for l in c] for c in cnf.clauses]
    for bits in range(1 << n):
        ok = True
        for clause in clauses:
            sat = False
            for (v, pos) in clause:
                val = (bits >> (v - 1)) & 1
                if (val == 1) == pos:
                    sat = True
                    break
            if not sat:
                ok = False
                break
        if ok:
            model = []
            for v in range(1, n + 1):
                val = (bits >> (v - 1)) & 1
                model.append(v if val else -v)
            return True, model
    return False, None


def count_models(cnf: CNF, var_limit: int = 20) -> int:
    """Count satisfying assignments (small instances only)."""
    n = cnf.nvars
    if n > var_limit:
        raise ValueError(f"model counting refuses {n} > {var_limit} variables")
    if any(len(c) == 0 for c in cnf.clauses):
        return 0
    clauses = [[(abs(l), l > 0) for l in c] for c in cnf.clauses]
    total = 0
    for bits in range(1 << n):
        ok = True
        for clause in clauses:
            if not any(((bits >> (v - 1)) & 1 == 1) == pos for (v, pos) in clause):
                ok = False
                break
        if ok:
            total += 1
    return total
