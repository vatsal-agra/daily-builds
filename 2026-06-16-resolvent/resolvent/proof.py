"""An independent DRUP-style UNSAT-proof checker.

A DRUP proof is a sequence of clauses the solver claims it learned, ending in
the empty clause. Each step must be a **RUP** (Reverse Unit Propagation)
consequence of the clauses accumulated so far: assuming the negation of the
new clause and running unit propagation to fixpoint must yield a conflict.

This checker is deliberately independent of the solver — it uses its own simple
(non-watched) propagation — so a passing check is real evidence of UNSAT.
"""
from __future__ import annotations

from typing import List, Sequence

from .cnf import CNF


def serialize_proof(proof: Sequence[Sequence[int]]) -> str:
    """Render a proof (list of clauses, possibly ending in the empty clause) as
    DRUP text — one clause per line, terminated by ``0``."""
    return "\n".join(" ".join(str(x) for x in clause) + " 0" for clause in proof) + "\n"


def parse_proof(text: str) -> List[List[int]]:
    proof = []
    cur: List[int] = []
    for tok in text.split():
        v = int(tok)
        if v == 0:
            proof.append(cur)
            cur = []
        else:
            cur.append(v)
    if cur:
        proof.append(cur)  # tolerate a missing final 0
    return proof


def _propagate_to_conflict(clauses: List[List[int]], assign: dict) -> bool:
    """Unit-propagate ``clauses`` under partial ``assign`` (var->bool). Return
    True iff a conflict (empty clause under assignment) is reached."""
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
                return True  # all literals false -> conflict
            if len(unassigned) == 1:
                lit = unassigned[0]
                assign[abs(lit)] = lit > 0
                changed = True
    return False


def check_rup(clauses: List[List[int]], new_clause: Sequence[int]) -> bool:
    """Is ``new_clause`` a RUP consequence of ``clauses``?"""
    assign = {}
    for lit in new_clause:  # assume the negation of the clause
        assign[abs(lit)] = not (lit > 0)
    if len(assign) < len({abs(l) for l in new_clause}):
        # clause contains x and -x simultaneously -> assuming its negation is
        # already contradictory; treat as trivially derivable.
        return True
    return _propagate_to_conflict(clauses, assign)


def check_proof(cnf: CNF, proof: Sequence[Sequence[int]]) -> bool:
    """Verify a DRUP proof against ``cnf``. Returns True iff every step is RUP and
    the proof derives the empty clause."""
    clauses = [list(c) for c in cnf.clauses]
    derived_empty = False
    for step in proof:
        step = list(step)
        if not check_rup(clauses, step):
            return False
        clauses.append(step)
        if len(step) == 0:
            derived_empty = True
            break
    return derived_empty
