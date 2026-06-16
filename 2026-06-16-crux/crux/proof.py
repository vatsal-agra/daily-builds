"""Independent UNSAT certificate checking (DRUP / reverse unit propagation).

When Crux proves a formula UNSAT it can emit a proof: the ordered sequence of
learned clauses it derived (plus clause-deletion hints), terminating in the empty
clause. This module *independently* verifies that certificate — it shares no code
with the solver's search — using the RUP (Reverse Unit Propagation) criterion:

    A clause C is RUP-implied by a set F of clauses iff assigning every literal of
    C to false and running unit propagation over F derives a conflict.

Every clause a CDCL solver learns is RUP-implied by the clauses present when it
was learned, and the final empty clause being RUP-implied certifies UNSAT.

We *ignore deletion hints* on purpose: keeping a superset of clauses can only make
unit propagation derive a conflict more easily, so every RUP check still passes
and the certificate stays sound, while sidestepping deletion-ordering fragility.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .cnf import CNF


def _rup_conflict(active: List[List[int]], assume_false: List[int]) -> bool:
    """True if assigning ``assume_false`` literals false then unit-propagating
    over ``active`` reaches a conflict."""
    value: Dict[int, bool] = {}
    for lit in assume_false:
        v = abs(lit)
        val = lit < 0  # literal forced false => var is (lit<0)
        if v in value and value[v] != val:
            return True
        value[v] = val

    changed = True
    while changed:
        changed = False
        for c in active:
            unassigned = []
            sat = False
            for lit in c:
                v = abs(lit)
                if v in value:
                    if value[v] == (lit > 0):
                        sat = True
                        break
                else:
                    unassigned.append(lit)
            if sat:
                continue
            if not unassigned:
                return True  # empty under assignment -> conflict
            if len(unassigned) == 1:
                lit = unassigned[0]
                value[abs(lit)] = lit > 0
                changed = True
    return False


def check_proof(cnf: CNF, proof: List[List[int]]) -> Tuple[bool, dict]:
    """Verify a DRUP-style proof certifies ``cnf`` UNSAT.

    ``proof`` is a list of steps: ``["a", *lits]`` adds a (RUP-implied) clause,
    ``["d", *lits]`` is a deletion hint (ignored here). An ``["a"]`` with no
    literals is the empty clause. Returns ``(ok, info)``.
    """
    active: List[List[int]] = [list(c) for c in cnf.clauses]
    steps = 0
    checked = 0
    derived_empty = False

    for step in proof:
        if not step:
            continue
        tag = step[0]
        lits = [int(x) for x in step[1:]]
        steps += 1
        if tag == "d":
            continue  # deletion hint ignored (sound: superset only helps RUP)
        if tag != "a":
            return False, {"steps": steps, "checked": checked,
                           "error": f"unknown proof tag {tag!r}"}
        checked += 1
        # RUP check: is this clause implied by the current active set?
        if not _rup_conflict(active, lits):
            return False, {"steps": steps, "checked": checked,
                           "error": f"clause {lits} is not RUP-implied",
                           "failed_clause": lits}
        if not lits:
            derived_empty = True
            break
        active.append(lits)

    if not derived_empty:
        # The solver may end without an explicit empty-clause step; the proof is
        # only a valid UNSAT certificate if the empty clause is itself RUP now.
        derived_empty = _rup_conflict(active, [])

    return derived_empty, {"steps": steps, "checked": checked,
                           "empty_derived": derived_empty}
