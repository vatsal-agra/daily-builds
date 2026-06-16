"""Independent DRAT/RUP proof checker for UNSAT certificates.

A CDCL solver derives an UNSAT result by learning a sequence of clauses ending
in the empty clause. Each learned clause has the **RUP** property (Reverse Unit
Propagation): assuming the negation of the clause's literals and running unit
propagation over the current clause database yields a conflict. A DRAT proof is
exactly that sequence of additions (deletions are an optimisation we can safely
ignore for *soundness* of the check).

This checker is written from scratch with its own, deliberately simple unit
propagation — it shares no code with the solver, so a bug in the solver cannot
hide a bug in the checker. If it accepts the proof, the formula really is UNSAT.
"""
from __future__ import annotations

from typing import List, Tuple, Optional


class ProofChecker:
    def __init__(self, num_vars: int, clauses: List[List[int]]):
        self.num_vars = num_vars
        self.clauses: List[List[int]] = [list(c) for c in clauses]

    def add_clause(self, c: List[int]) -> None:
        self.clauses.append(list(c))

    def _is_rup(self, clause: List[int]) -> bool:
        """True iff `clause` is implied by the current DB via reverse unit prop."""
        assign = {}  # var -> bool

        def val(l: int) -> Optional[bool]:
            a = assign.get(abs(l))
            if a is None:
                return None
            return a if l > 0 else (not a)

        # Seed: assume every literal of `clause` is false.
        for l in clause:
            cur = val(l)
            if cur is True:
                # forcing l false but l already forced true => `clause` contains
                # both l and ~l (a tautology) => trivially implied.
                return True
            assign[abs(l)] = (l < 0)  # make l false

        # Unit propagation to fixpoint.
        changed = True
        while changed:
            changed = False
            for cl in self.clauses:
                unassigned: List[int] = []
                satisfied = False
                for l in cl:
                    v = val(l)
                    if v is True:
                        satisfied = True
                        break
                    if v is None:
                        unassigned.append(l)
                        if len(unassigned) > 1:
                            break
                if satisfied:
                    continue
                if not unassigned:
                    return True  # empty clause under assignment => conflict
                if len(unassigned) == 1:
                    u = unassigned[0]
                    assign[abs(u)] = (u > 0)
                    changed = True
        return False

    def check(self, proof: List[List[int]]) -> Tuple[bool, str]:
        """Verify a proof (sequence of added clauses). Returns (ok, message)."""
        derived_empty = False
        for idx, c in enumerate(proof):
            if not self._is_rup(c):
                return False, f"proof step {idx} is not RUP: clause {c}"
            self.add_clause(c)
            if len(c) == 0:
                derived_empty = True
                break
        if derived_empty:
            return True, f"UNSAT verified ({len(proof)} proof steps checked)"
        # No explicit empty clause; the proof is valid only if the empty clause
        # is itself RUP w.r.t. the final database.
        if self._is_rup([]):
            return True, "UNSAT verified (empty clause is RUP after proof)"
        return False, "proof does not derive the empty clause"


def verify_unsat(num_vars: int, clauses: List[List[int]],
                 proof: List[List[int]]) -> Tuple[bool, str]:
    return ProofChecker(num_vars, clauses).check(proof)


# ---- DRAT text format (interchange) -------------------------------------
def proof_to_drat(proof: List[List[int]]) -> str:
    return "".join(" ".join(map(str, c)) + " 0\n" for c in proof)


def drat_from_text(text: str) -> List[List[int]]:
    out: List[List[int]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("d"):
            continue  # deletion — ignored (sound for RUP checking)
        cur: List[int] = []
        for tok in line.split():
            t = int(tok)
            if t == 0:
                out.append(cur)
                cur = []
            else:
                cur.append(t)
    return out
