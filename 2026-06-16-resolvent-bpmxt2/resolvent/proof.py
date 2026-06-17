"""Verification: a brute-force oracle, an exact #SAT model counter, and an
independent DRAT-style UNSAT proof checker (reverse unit propagation).

The proof checker is deliberately *separate* from the solver: it re-derives the
empty clause from the original formula plus the solver's learned clauses using
only unit propagation, so an UNSAT verdict does not require trusting the solver.
"""
from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Tuple

from .cnf import CNF


# ---------------------------------------------------------------------- #
# brute-force oracle + exact model counter                               #
# ---------------------------------------------------------------------- #
def brute_force_sat(cnf: CNF) -> bool:
    """Exponential reference: True iff some assignment satisfies the formula."""
    # repeat=0 yields a single empty assignment, which correctly handles the
    # 0-variable case (SAT unless an empty clause is present).
    for bits in itertools.product((False, True), repeat=cnf.nvars):
        model = {i + 1: bits[i] for i in range(cnf.nvars)}
        if cnf.is_satisfied_by(model):
            return True
    return False


def count_models_bruteforce(cnf: CNF) -> int:
    total = 0
    for bits in itertools.product((False, True), repeat=cnf.nvars):
        model = {i + 1: bits[i] for i in range(cnf.nvars)}
        if cnf.is_satisfied_by(model):
            total += 1
    return total


def count_models_dpll(cnf: CNF) -> int:
    """Exact #SAT via DPLL with unit propagation, counting over *all* nvars
    variables (free variables contribute a factor of 2)."""
    clauses = [list(c) for c in cnf.clauses]
    n = cnf.nvars
    return _dpll_count(clauses, {}, n)


def _dpll_count(clauses: List[List[int]], assign: Dict[int, bool], n: int) -> int:
    # unit propagation
    assign = dict(assign)
    changed = True
    while changed:
        changed = False
        for c in clauses:
            unassigned = []
            satisfied = False
            for lit in c:
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
                return 0  # conflict
            if len(unassigned) == 1:
                lit = unassigned[0]
                assign[abs(lit)] = (lit > 0)
                changed = True
    # simplify: drop satisfied clauses; collect remaining vars
    remaining: List[List[int]] = []
    for c in clauses:
        sat = False
        rem = []
        for lit in c:
            v = abs(lit)
            if v in assign:
                if assign[v] == (lit > 0):
                    sat = True
                    break
            else:
                rem.append(lit)
        if sat:
            continue
        if not rem:
            return 0
        remaining.append(rem)
    if not remaining:
        free = n - len(assign)
        return 1 << free
    # branch on the first literal of the smallest clause
    pivot = abs(min(remaining, key=len)[0])
    total = 0
    for val in (False, True):
        a2 = dict(assign)
        a2[pivot] = val
        total += _dpll_count(remaining, a2, n)
    return total


# ---------------------------------------------------------------------- #
# DRAT-style proof: reverse unit propagation checker                     #
# ---------------------------------------------------------------------- #
def _unit_propagate(clauses: List[List[int]], assign: Dict[int, bool]) -> bool:
    """Return True if unit propagation derives a conflict from ``assign``."""
    changed = True
    while changed:
        changed = False
        for c in clauses:
            unassigned = None
            count_unassigned = 0
            satisfied = False
            for lit in c:
                v = abs(lit)
                if v in assign:
                    if assign[v] == (lit > 0):
                        satisfied = True
                        break
                else:
                    count_unassigned += 1
                    unassigned = lit
                    if count_unassigned > 1:
                        break
            if satisfied:
                continue
            if count_unassigned == 0:
                return True  # conflict
            if count_unassigned == 1:
                assign[abs(unassigned)] = (unassigned > 0)
                changed = True
    return False


def is_rup(clause: List[int], clauses: List[List[int]]) -> bool:
    """Reverse Unit Propagation: True iff assuming the negation of every literal
    in ``clause`` and unit-propagating over ``clauses`` yields a conflict.

    This certifies that ``clause`` is implied by ``clauses``.
    """
    assign: Dict[int, bool] = {}
    for lit in clause:
        v = abs(lit)
        want = (lit < 0)  # negate the literal
        if v in assign and assign[v] != want:
            return True  # the assumption set is itself contradictory
        assign[v] = want
    return _unit_propagate([list(c) for c in clauses], assign)


def check_proof(cnf: CNF, proof: List[Tuple[str, List[int]]]) -> Tuple[bool, str]:
    """Independently verify a DRAT-style proof of UNSAT.

    Each proof step is ('a', clause) for an addition or ('d', clause) for a
    deletion. Every added clause must be RUP w.r.t. the current clause set.
    The proof is valid iff it ends by adding the empty clause.

    Returns (ok, message).
    """
    clauses: List[List[int]] = [list(c) for c in cnf.clauses]
    derived_empty = False
    for step_no, (kind, clause) in enumerate(proof):
        if kind == "d":
            # remove one matching clause if present (order-insensitive)
            target = sorted(clause)
            for i, c in enumerate(clauses):
                if sorted(c) == target:
                    clauses.pop(i)
                    break
            continue
        if kind != "a":
            return False, f"step {step_no}: unknown proof directive {kind!r}"
        if not is_rup(clause, clauses):
            return False, (f"step {step_no}: clause {clause} is not RUP — "
                           f"proof is INVALID")
        clauses.append(list(clause))
        if len(clause) == 0:
            derived_empty = True
            break
    if not derived_empty:
        return False, "proof does not derive the empty clause"
    return True, "proof valid: empty clause derived by reverse unit propagation"
