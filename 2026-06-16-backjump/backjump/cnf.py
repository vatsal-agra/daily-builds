"""CNF representation and DIMACS I/O.

A literal is a nonzero int: positive for a variable, negative for its negation.
A clause is a list of literals.  A CNF is a conjunction of clauses over
variables 1..num_vars.
"""

from __future__ import annotations

from typing import List, Iterable, TextIO


class CNF:
    def __init__(self, num_vars: int = 0, clauses: Iterable[List[int]] | None = None):
        self.num_vars = num_vars
        self.clauses: List[List[int]] = []
        if clauses:
            for c in clauses:
                self.add_clause(c)

    def add_clause(self, lits: Iterable[int]) -> None:
        clause = list(lits)
        for lit in clause:
            if lit == 0:
                raise ValueError("0 is not a valid literal")
            v = abs(lit)
            if v > self.num_vars:
                self.num_vars = v
        self.clauses.append(clause)

    def new_var(self) -> int:
        self.num_vars += 1
        return self.num_vars

    @property
    def num_clauses(self) -> int:
        return len(self.clauses)

    def copy(self) -> "CNF":
        out = CNF(self.num_vars)
        out.clauses = [list(c) for c in self.clauses]
        return out

    def to_dimacs(self) -> str:
        lines = [f"p cnf {self.num_vars} {len(self.clauses)}"]
        for c in self.clauses:
            lines.append(" ".join(str(l) for l in c) + " 0")
        return "\n".join(lines) + "\n"

    def __repr__(self) -> str:
        return f"CNF(num_vars={self.num_vars}, num_clauses={len(self.clauses)})"


def parse_dimacs(text: str) -> CNF:
    """Parse DIMACS CNF text.  Tolerant of comments, blank lines, and clauses
    spanning multiple lines (terminated by 0)."""
    cnf = CNF()
    declared_vars = None
    declared_clauses = None
    tokens: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p"):
            parts = line.split()
            if len(parts) < 4 or parts[1] != "cnf":
                raise ValueError(f"bad problem line: {raw!r}")
            declared_vars = int(parts[2])
            declared_clauses = int(parts[3])
            continue
        if line.startswith("%"):  # some files have a trailing % terminator
            break
        tokens.extend(line.split())

    cur: List[int] = []
    for tok in tokens:
        try:
            n = int(tok)
        except ValueError:
            raise ValueError(f"not valid DIMACS: expected an integer literal, got {tok!r}")
        if n == 0:
            cnf.add_clause(cur)
            cur = []
        else:
            cur.append(n)
    if cur:
        # trailing clause without terminating 0 — accept it
        cnf.add_clause(cur)

    if declared_vars is not None and declared_vars > cnf.num_vars:
        cnf.num_vars = declared_vars
    if declared_clauses is not None and declared_clauses != len(cnf.clauses):
        # not fatal, but worth surfacing in strict contexts
        cnf.declared_clause_mismatch = (declared_clauses, len(cnf.clauses))  # type: ignore[attr-defined]
    return cnf


def write_dimacs(cnf: CNF, out: TextIO) -> None:
    out.write(cnf.to_dimacs())
