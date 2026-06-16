"""Exact model counting (#SAT) via DPLL with unit propagation.

Counts the number of satisfying assignments over *all* ``nvars`` declared
variables (a variable that appears in no remaining clause contributes a factor of
two, the standard #SAT convention). Intended for small/medium instances and
cross-checked against the brute-force counter in tests.
"""

from __future__ import annotations

from collections import Counter
from typing import List, Optional

from .cnf import CNF


def model_count(cnf: CNF) -> int:
    nvars = cnf.nvars
    value: List[Optional[bool]] = [None] * (nvars + 1)
    return _count([list(c) for c in cnf.clauses], value, nvars)


def _count(clauses: List[List[int]], value: List[Optional[bool]], nvars: int) -> int:
    value = value[:]

    # --- unit propagation -------------------------------------------------
    changed = True
    while changed:
        changed = False
        for c in clauses:
            unassigned = []
            sat = False
            for lit in c:
                v = value[abs(lit)]
                if v is None:
                    unassigned.append(lit)
                elif v == (lit > 0):
                    sat = True
                    break
            if sat:
                continue
            if not unassigned:
                return 0  # conflict: this branch contributes nothing
            if len(unassigned) == 1:
                lit = unassigned[0]
                value[abs(lit)] = lit > 0
                changed = True

    # --- build residual (unsatisfied) clauses -----------------------------
    residual: List[List[int]] = []
    for c in clauses:
        rest = []
        sat = False
        for lit in c:
            v = value[abs(lit)]
            if v is None:
                rest.append(lit)
            elif v == (lit > 0):
                sat = True
                break
        if sat:
            continue
        if not rest:
            return 0
        residual.append(rest)

    assigned = sum(1 for i in range(1, nvars + 1) if value[i] is not None)
    if not residual:
        # every remaining variable is free -> 2 choices each
        return 1 << (nvars - assigned)

    # --- branch on the most frequent variable -----------------------------
    freq = Counter(abs(l) for c in residual for l in c)
    var = freq.most_common(1)[0][0]
    total = 0
    for val in (True, False):
        v2 = value[:]
        v2[var] = val
        total += _count(residual, v2, nvars)
    return total
