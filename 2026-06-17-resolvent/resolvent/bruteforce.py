"""An intentionally simple, obviously-correct SAT oracle used to differentially
test the real CDCL solver. Two independent strategies:

* ``truth_table_sat`` — brute force over all 2**n assignments (n small).
* ``dpll_sat`` — textbook recursive DPLL with unit propagation, no learning.

If the fast CDCL solver ever disagrees with these on satisfiability, something
is wrong with the fast solver.
"""
from __future__ import annotations

from typing import List, Optional, Dict
from .cnf import CNF


def truth_table_sat(formula: CNF) -> bool:
    n = formula.nvars
    for bits in range(1 << n):
        assign = {v: bool((bits >> (v - 1)) & 1) for v in range(1, n + 1)}
        if formula.is_satisfied_by(assign):
            return True
    return n == 0  # the empty formula (no vars, no clauses) is SAT


def find_model_truth_table(formula: CNF) -> Optional[Dict[int, bool]]:
    n = formula.nvars
    for bits in range(1 << n):
        assign = {v: bool((bits >> (v - 1)) & 1) for v in range(1, n + 1)}
        if formula.is_satisfied_by(assign):
            return assign
    return {} if (n == 0 and not formula.clauses) else None


def dpll_sat(formula: CNF) -> bool:
    clauses = [list(c) for c in formula.clauses]
    return _dpll(clauses, {}, formula.nvars)


def _dpll(clauses: List[List[int]], assign: Dict[int, bool], nvars: int) -> bool:
    # Unit propagation.
    assign = dict(assign)
    changed = True
    while changed:
        changed = False
        for clause in clauses:
            unassigned = []
            satisfied = False
            for lit in clause:
                v = abs(lit)
                if v in assign:
                    if assign[v] == (lit > 0):
                        satisfied = True
                        break
                else:
                    unassigned.append(lit)
            if satisfied:
                continue
            if not unassigned:
                return False  # empty (falsified) clause
            if len(unassigned) == 1:
                lit = unassigned[0]
                assign[abs(lit)] = (lit > 0)
                changed = True
    # All clauses satisfied?
    all_sat = True
    next_var = None
    for clause in clauses:
        sat = False
        for lit in clause:
            v = abs(lit)
            if v in assign and assign[v] == (lit > 0):
                sat = True
                break
        if not sat:
            all_sat = False
            for lit in clause:
                if abs(lit) not in assign:
                    next_var = abs(lit)
                    break
            if next_var is not None:
                break
    if all_sat:
        return True
    if next_var is None:
        return False
    for val in (True, False):
        a2 = dict(assign)
        a2[next_var] = val
        if _dpll(clauses, a2, nvars):
            return True
    return False
