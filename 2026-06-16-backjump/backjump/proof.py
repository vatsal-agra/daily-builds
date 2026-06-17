"""Independent answer verification.

  * ``check_model``  — confirm a model satisfies every clause (for SAT answers).
  * ``check_proof``  — verify a DRUP-style UNSAT proof: the proof is the list of
    clauses the solver learned, in derivation order, ending with the empty
    clause.  Each clause must be a *reverse unit propagation* (RUP) consequence
    of the original formula plus the clauses derived before it, and the final
    empty clause certifies the contradiction.

This module shares NO code with the solver — it has its own, deliberately simple,
unit-propagation engine — so it is a true independent check.  A solver that wrongly
reports UNSAT cannot produce a proof that passes here.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Tuple


def check_model(clauses: List[List[int]], model) -> bool:
    """Return True iff every clause has at least one true literal under `model`.

    `model` may be a list of signed literals or a dict var->bool.
    """
    if isinstance(model, dict):
        val = model
    else:
        val = {}
        for lit in model:
            val[abs(lit)] = lit > 0
    for clause in clauses:
        ok = False
        for lit in clause:
            v = val.get(abs(lit))
            if v is None:
                continue
            if (v and lit > 0) or ((not v) and lit < 0):
                ok = True
                break
        if not ok:
            return False
    return True


class _Propagator:
    """Plain unit-propagation over a growing clause set, with occurrence lists."""

    def __init__(self):
        self.clauses: List[List[int]] = []
        self.occ: Dict[int, List[int]] = {}

    def add(self, clause: List[int]) -> bool:
        """Add a clause (deduping literals and dropping tautologies, so duplicate
        literals propagate correctly).  Returns True if the clause was kept."""
        seen = set()
        lits: List[int] = []
        for l in clause:
            if -l in seen:
                return False  # tautology: always satisfied, never propagates
            if l not in seen:
                seen.add(l)
                lits.append(l)
        ci = len(self.clauses)
        self.clauses.append(lits)
        for lit in lits:
            self.occ.setdefault(lit, []).append(ci)
        return True

    def _propagate(self, assign: Dict[int, bool], trail: List[int]) -> bool:
        """Propagate to fixpoint.  Returns True iff a conflict is reached."""
        qi = 0
        while qi < len(trail):
            true_lit = trail[qi]
            qi += 1
            # clauses containing the negation of `true_lit` may have shrunk
            for ci in self.occ.get(-true_lit, ()):  # type: ignore[arg-type]
                clause = self.clauses[ci]
                unassigned: Optional[int] = None
                count = 0
                satisfied = False
                for l in clause:
                    val = assign.get(abs(l))
                    if val is None:
                        count += 1
                        unassigned = l
                        if count > 1:
                            break
                    elif (val and l > 0) or ((not val) and l < 0):
                        satisfied = True
                        break
                if satisfied or count > 1:
                    continue
                if count == 0:
                    return True  # conflict: all literals false
                v = abs(unassigned)  # type: ignore[arg-type]
                if assign.get(v) is None:
                    assign[v] = unassigned > 0  # type: ignore[operator]
                    trail.append(unassigned)  # type: ignore[arg-type]
        return False

    def rup(self, clause: List[int]) -> bool:
        """Return True iff `clause` is implied by the current set via RUP."""
        assign: Dict[int, bool] = {}
        trail: List[int] = []
        # assume the negation of every literal in `clause`
        for lit in clause:
            v = abs(lit)
            want = lit < 0  # negate the literal
            if v in assign and assign[v] != want:
                return True  # assumptions already contradict
            assign[v] = want
            trail.append(-lit)
        # seed with the formula's existing unit clauses
        for cl in self.clauses:
            if len(cl) == 1:
                l = cl[0]
                v = abs(l)
                if v not in assign:
                    assign[v] = l > 0
                    trail.append(l)
                elif assign[v] != (l > 0):
                    return True
        return self._propagate(assign, trail)


def check_proof(original: List[List[int]], proof: List[List[int]]) -> Tuple[bool, str]:
    """Verify a DRUP-style proof.  Returns (ok, message)."""
    prop = _Propagator()
    for clause in original:
        prop.add(list(clause))
        if len(clause) == 0:
            return True, "original formula contains the empty clause"

    if not proof:
        return False, "empty proof (no refutation provided)"
    if proof[-1] != []:
        return False, "proof does not end with the empty clause"

    for idx, clause in enumerate(proof):
        if not prop.rup(clause):
            return False, (
                f"proof step {idx} is not RUP: clause {clause} is not implied "
                f"by the formula derived so far"
            )
        prop.add(list(clause))

    return True, "proof verified: empty clause derived by reverse unit propagation"
