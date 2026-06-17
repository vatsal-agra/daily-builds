"""CNF formula representation plus a strict DIMACS reader/writer.

A *literal* is a non-zero signed integer: ``3`` means variable 3 is true,
``-3`` means variable 3 is false. A *clause* is a list of literals (a
disjunction). A *formula* is a conjunction of clauses.
"""
from __future__ import annotations

from typing import List, Iterable, TextIO


class DimacsError(ValueError):
    """Raised when DIMACS input is malformed, with a 1-based line number."""

    def __init__(self, line_no: int, message: str):
        self.line_no = line_no
        super().__init__(f"line {line_no}: {message}")


class CNF:
    """A CNF formula: a list of clauses over variables ``1..nvars``."""

    def __init__(self, nvars: int = 0, clauses: Iterable[List[int]] | None = None):
        self.nvars = nvars
        self.clauses: List[List[int]] = []
        if clauses is not None:
            for c in clauses:
                self.add_clause(c)

    def add_clause(self, lits: Iterable[int]) -> None:
        clause: List[int] = []
        seen = set()
        for lit in lits:
            if lit == 0:
                raise ValueError("0 is not a valid literal")
            v = abs(lit)
            if v > self.nvars:
                self.nvars = v
            if -lit in seen:
                # Clause contains both x and -x: it is a tautology, always
                # satisfied. Dropping it preserves satisfiability exactly.
                return
            if lit in seen:
                continue  # duplicate literal, ignore
            seen.add(lit)
            clause.append(lit)
        self.clauses.append(clause)

    @property
    def nclauses(self) -> int:
        return len(self.clauses)

    def copy(self) -> "CNF":
        f = CNF(self.nvars)
        f.clauses = [list(c) for c in self.clauses]
        return f

    def is_satisfied_by(self, assignment) -> bool:
        """True iff ``assignment`` (a dict var->bool or 1-indexed list) makes
        every clause true. Variables absent from the assignment are treated as
        false for the purpose of this check (callers should supply full ones)."""
        def val(lit: int) -> bool:
            v = abs(lit)
            if isinstance(assignment, dict):
                b = assignment.get(v, False)
            else:
                b = assignment[v] if v < len(assignment) else False
            return b if lit > 0 else not b

        for clause in self.clauses:
            if not any(val(lit) for lit in clause):
                return False
        return True

    def to_dimacs(self) -> str:
        out = [f"p cnf {self.nvars} {self.nclauses}"]
        for clause in self.clauses:
            out.append(" ".join(str(l) for l in clause) + " 0")
        return "\n".join(out) + "\n"

    def write_dimacs(self, fh: TextIO) -> None:
        fh.write(self.to_dimacs())

    @classmethod
    def parse_dimacs(cls, text: str) -> "CNF":
        """Parse DIMACS CNF. Tolerant of clauses spanning multiple lines and of
        a missing/loose header, but strict about malformed tokens."""
        declared_vars = None
        declared_clauses = None
        clauses: List[List[int]] = []
        current: List[int] = []
        header_seen = False
        max_var = 0

        for line_no, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            if line[0] == 'c':
                continue
            if line[0] == 'p':
                if header_seen:
                    raise DimacsError(line_no, "duplicate 'p' header")
                parts = line.split()
                if len(parts) != 4 or parts[1] != 'cnf':
                    raise DimacsError(line_no, "header must be 'p cnf <vars> <clauses>'")
                try:
                    declared_vars = int(parts[2])
                    declared_clauses = int(parts[3])
                except ValueError:
                    raise DimacsError(line_no, "header counts must be integers")
                if declared_vars < 0 or declared_clauses < 0:
                    raise DimacsError(line_no, "header counts must be non-negative")
                header_seen = True
                continue
            if line[0] == '%':
                break  # some DIMACS files have a trailing '%' / '0' marker
            for tok in line.split():
                try:
                    n = int(tok)
                except ValueError:
                    raise DimacsError(line_no, f"non-integer token {tok!r}")
                if n == 0:
                    clauses.append(current)
                    current = []
                else:
                    v = abs(n)
                    if v > max_var:
                        max_var = v
                    current.append(n)
        if current:
            # Trailing clause without a terminating 0.
            clauses.append(current)

        if declared_vars is not None and max_var > declared_vars:
            raise DimacsError(0, f"variable {max_var} exceeds declared count {declared_vars}")

        nvars = declared_vars if declared_vars is not None else max_var
        f = cls(nvars)
        for c in clauses:
            f.add_clause(c)
        if declared_clauses is not None and len(clauses) != declared_clauses:
            # Not fatal (many real files miscount), but record it.
            f.header_clause_mismatch = (declared_clauses, len(clauses))
        return f


def read_dimacs_file(path: str) -> CNF:
    with open(path, "r") as fh:
        return CNF.parse_dimacs(fh.read())
