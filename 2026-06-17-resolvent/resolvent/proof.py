"""An independent checker for UNSAT proofs emitted by the solver.

When asked, the CDCL solver records every learned clause in order; on UNSAT it
appends the empty clause. That sequence is a DRAT-style proof. Each step is
verified here by the **RUP (Reverse Unit Propagation)** property: a clause C is
implied by a formula F if assuming every literal of C false and running *unit
propagation alone* on F derives a conflict. We add each verified clause to the
accumulated formula and continue; if the final empty clause is RUP, the original
formula is unsatisfiable.

Crucially this module shares no search logic with the solver — only the CNF data
structure — so it is a genuine cross-check, not a self-certification.
"""
from __future__ import annotations

from typing import List, Tuple, Dict
from .cnf import CNF


def _unit_propagate(clauses: List[List[int]], assign: Dict[int, bool]) -> bool:
    """Run unit propagation from the seed assignment. Returns True iff a
    conflict (an all-false clause) is derived. ``assign`` maps var -> bool."""
    def lit_state(lit: int):
        v = abs(lit)
        if v not in assign:
            return None
        return assign[v] == (lit > 0)

    changed = True
    while changed:
        changed = False
        for clause in clauses:
            unassigned = None
            count_unassigned = 0
            satisfied = False
            for lit in clause:
                st = lit_state(lit)
                if st is True:
                    satisfied = True
                    break
                if st is None:
                    count_unassigned += 1
                    unassigned = lit
                    if count_unassigned > 1:
                        break
            if satisfied:
                continue
            if count_unassigned == 0:
                return True  # all literals false -> conflict
            if count_unassigned == 1:
                v = abs(unassigned)
                assign[v] = (unassigned > 0)
                changed = True
    return False


def rup_implied(clauses: List[List[int]], candidate: List[int]) -> bool:
    """Is ``candidate`` derivable from ``clauses`` by reverse unit propagation?"""
    assign: Dict[int, bool] = {}
    for lit in candidate:
        v = abs(lit)
        want = (lit < 0)  # negate the literal: make it false
        if v in assign and assign[v] != want:
            return True  # candidate already contains x and ¬x: trivially implied
        assign[v] = want
    return _unit_propagate([list(c) for c in clauses], assign)


def check_unsat_proof(formula: CNF, proof: List[List[int]]) -> Tuple[bool, str]:
    """Verify a clausal proof of unsatisfiability.

    Returns (ok, message). ``ok`` is True iff every proof clause is RUP-implied
    by the accumulated formula and the proof ends in the empty clause.
    """
    if not proof or proof[-1] != []:
        return False, "proof does not end in the empty clause"
    accumulated: List[List[int]] = [list(c) for c in formula.clauses]
    for step, clause in enumerate(proof):
        if not rup_implied(accumulated, clause):
            shown = "empty clause" if clause == [] else f"clause {clause}"
            return (False, f"step {step}: {shown} is not RUP-implied "
                           "by the accumulated formula")
        accumulated.append(list(clause))
    return (True,
            f"all {len(proof)} steps RUP-checked; the empty clause is derivable, "
            "so the formula is unsatisfiable")
