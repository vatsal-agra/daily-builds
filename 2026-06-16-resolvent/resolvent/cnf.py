"""CNF representation, DIMACS I/O, and model checking.

A literal is a non-zero int in DIMACS convention: ``v`` for the positive
literal of variable ``v`` and ``-v`` for its negation. A clause is a list of
literals (a disjunction). A formula is a conjunction of clauses.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence


class CNF:
    """A CNF formula: ``nvars`` variables (1..nvars) and a list of clauses."""

    def __init__(self, nvars: int = 0, clauses: Optional[List[List[int]]] = None):
        self.nvars = nvars
        self.clauses: List[List[int]] = []
        if clauses:
            for c in clauses:
                self.add_clause(c)

    def new_var(self) -> int:
        self.nvars += 1
        return self.nvars

    def add_clause(self, lits: Iterable[int]) -> None:
        clause = [int(x) for x in lits]
        for lit in clause:
            if lit == 0:
                raise ValueError("0 is not a valid literal")
            self.nvars = max(self.nvars, abs(lit))
        self.clauses.append(clause)

    # ------------------------------------------------------------------ #
    # DIMACS                                                             #
    # ------------------------------------------------------------------ #
    @classmethod
    def from_dimacs(cls, text: str) -> "CNF":
        """Parse DIMACS CNF text. Tolerant of comments and arbitrary spacing."""
        nvars = 0
        nclauses_decl = None
        clauses: List[List[int]] = []
        cur: List[int] = []
        saw_header = False
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                if len(parts) < 4 or parts[1] != "cnf":
                    raise ValueError(f"bad DIMACS header: {line!r}")
                nvars = int(parts[2])
                nclauses_decl = int(parts[3])
                saw_header = True
                continue
            if line.startswith("%"):  # some files append a trailing % / 0
                break
            for tok in line.split():
                val = int(tok)
                if val == 0:
                    clauses.append(cur)
                    cur = []
                else:
                    cur.append(val)
                    nvars = max(nvars, abs(val))
        if cur:  # final clause without trailing 0
            clauses.append(cur)
        f = cls(nvars)
        f.clauses = clauses
        if not saw_header and not clauses:
            # truly empty input -> trivially satisfiable empty formula
            pass
        if nclauses_decl is not None and nclauses_decl != len(clauses):
            # not fatal: many real files miscount, but record it
            f.header_clause_count = nclauses_decl  # type: ignore[attr-defined]
        return f

    def to_dimacs(self, comment: Optional[str] = None) -> str:
        out: List[str] = []
        if comment:
            for line in comment.splitlines():
                out.append(f"c {line}")
        out.append(f"p cnf {self.nvars} {len(self.clauses)}")
        for c in self.clauses:
            out.append(" ".join(str(l) for l in c) + " 0")
        return "\n".join(out) + "\n"

    # ------------------------------------------------------------------ #
    # Model checking                                                     #
    # ------------------------------------------------------------------ #
    def is_satisfied_by(self, model: Dict[int, bool]) -> bool:
        """True iff ``model`` (var -> bool) satisfies every clause."""
        for c in self.clauses:
            if not self._clause_true(c, model):
                return False
        return True

    def first_unsatisfied(self, model: Dict[int, bool]) -> Optional[List[int]]:
        for c in self.clauses:
            if not self._clause_true(c, model):
                return c
        return None

    @staticmethod
    def _clause_true(clause: Sequence[int], model: Dict[int, bool]) -> bool:
        if not clause:
            return False  # empty clause is always false
        for lit in clause:
            v = abs(lit)
            if v in model and model[v] == (lit > 0):
                return True
        return False

    def __repr__(self) -> str:
        return f"CNF(nvars={self.nvars}, nclauses={len(self.clauses)})"
