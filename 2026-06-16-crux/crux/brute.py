"""Reference solvers used as an independent oracle for Crux.

These are deliberately simple and obviously-correct (at the cost of speed): an
exhaustive truth-table search for satisfiability and an exact model *count*.
They exist so the fast CDCL engine can be differentially tested against an
implementation that shares none of its machinery.
"""

from __future__ import annotations

from itertools import product
from typing import Dict, List, Optional

from .cnf import CNF


def _clause_sat(clause, assign: Dict[int, bool]) -> bool:
    for lit in clause:
        if assign[abs(lit)] == (lit > 0):
            return True
    return False


def brute_solve(cnf: CNF) -> Optional[Dict[int, bool]]:
    """Return a satisfying assignment {var: bool} or None if UNSAT.

    Exhaustive over all 2**nvars assignments — only for small instances.
    """
    vs = cnf.variables()
    if not vs:
        # no variables: SAT iff there are no (empty) clauses
        return {} if all(len(c) > 0 for c in cnf.clauses) else None
    for bits in product((False, True), repeat=len(vs)):
        assign = dict(zip(vs, bits))
        # variables that appear in no clause are irrelevant; default any missing
        full = {v: assign.get(v, False) for v in range(1, cnf.nvars + 1)}
        if all(_clause_sat(c, full) for c in cnf.clauses):
            return full
    return None


def brute_is_sat(cnf: CNF) -> bool:
    return brute_solve(cnf) is not None


def brute_count(cnf: CNF) -> int:
    """Exact #SAT: number of satisfying assignments over all ``nvars`` variables.

    Variables not occurring in any clause still double the count (each can be
    either value), matching standard #SAT semantics over the declared variables.
    """
    n = cnf.nvars
    if n == 0:
        return 1 if all(len(c) > 0 for c in cnf.clauses) else 0
    count = 0
    for bits in product((False, True), repeat=n):
        assign = {i + 1: bits[i] for i in range(n)}
        if all(_clause_sat(c, assign) for c in cnf.clauses):
            count += 1
    return count
