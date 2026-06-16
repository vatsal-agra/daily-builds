"""CNF model + a tolerant DIMACS front-end.

Literals are signed non-zero integers (DIMACS convention): variable ``v >= 1``,
positive literal ``v``, negative literal ``-v``. A clause is a list of literals
(a disjunction); a CNF is a conjunction of clauses.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence


class DimacsError(Exception):
    """Raised on malformed DIMACS input, with a line/column pointer."""

    def __init__(self, msg: str, lineno: int, line: str = "", col: int | None = None):
        self.msg = msg
        self.lineno = lineno
        self.line = line
        self.col = col
        super().__init__(self._render())

    def _render(self) -> str:
        out = [f"DIMACS parse error (line {self.lineno}): {self.msg}"]
        if self.line:
            out.append(f"  {self.line.rstrip()}")
            if self.col is not None:
                out.append("  " + " " * self.col + "^")
        return "\n".join(out)


class CNF:
    """A CNF formula: a fixed number of variables and a list of clauses."""

    def __init__(self, nvars: int = 0, clauses: Iterable[Sequence[int]] | None = None):
        self.nvars = int(nvars)
        self.clauses: List[List[int]] = []
        if clauses:
            for c in clauses:
                self.add_clause(c)

    # -- construction -----------------------------------------------------
    def new_var(self) -> int:
        """Allocate and return a fresh variable id."""
        self.nvars += 1
        return self.nvars

    def add_clause(self, lits: Sequence[int]) -> "CNF":
        """Add a clause (list of non-zero int literals). Tracks variable count."""
        clause: List[int] = []
        for lit in lits:
            lit = int(lit)
            if lit == 0:
                raise ValueError("0 is not a valid literal (it is the DIMACS terminator)")
            v = abs(lit)
            if v > self.nvars:
                self.nvars = v
            clause.append(lit)
        self.clauses.append(clause)
        return self

    def extend(self, clauses: Iterable[Sequence[int]]) -> "CNF":
        for c in clauses:
            self.add_clause(c)
        return self

    # -- queries ----------------------------------------------------------
    @property
    def nclauses(self) -> int:
        return len(self.clauses)

    def is_satisfied_by(self, model: Sequence[int]) -> bool:
        """True iff ``model`` (a list of signed literals / truth assignment) satisfies all clauses."""
        truth = {}
        for lit in model:
            if lit == 0:
                continue
            truth[abs(lit)] = lit > 0
        for clause in self.clauses:
            ok = False
            for lit in clause:
                v = abs(lit)
                if v in truth and truth[v] == (lit > 0):
                    ok = True
                    break
            if not ok:
                return False
        return True

    # -- serialization ----------------------------------------------------
    def to_dimacs(self, comment: str | None = None) -> str:
        lines = []
        if comment:
            for cl in comment.splitlines():
                lines.append(f"c {cl}")
        lines.append(f"p cnf {self.nvars} {self.nclauses}")
        for clause in self.clauses:
            lines.append(" ".join(str(x) for x in clause) + " 0")
        return "\n".join(lines) + "\n"

    def __repr__(self) -> str:
        return f"CNF(nvars={self.nvars}, nclauses={self.nclauses})"


def parse_dimacs(text: str) -> CNF:
    """Parse DIMACS CNF text into a :class:`CNF`.

    Tolerant of: ``c`` comment lines, blank lines, clauses split across lines,
    extra whitespace, and a trailing ``%``/``0`` block (SATLIB style). Strict
    about: missing header, non-integer tokens, and clauses with no terminating 0.
    """
    lines = text.splitlines()
    header_seen = False
    declared_vars = None
    declared_clauses = None
    cnf = CNF()
    cur: List[int] = []
    cur_started_line = 0

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("c"):
            continue
        if line.startswith("%"):
            # SATLIB end-of-formula marker; ignore the rest of the file.
            break
        if line.startswith("p"):
            if header_seen:
                raise DimacsError("duplicate problem header", lineno, raw)
            parts = line.split()
            if len(parts) != 4 or parts[1] != "cnf":
                raise DimacsError(
                    "header must be 'p cnf <vars> <clauses>'", lineno, raw
                )
            try:
                declared_vars = int(parts[2])
                declared_clauses = int(parts[3])
            except ValueError:
                raise DimacsError("header counts must be integers", lineno, raw)
            if declared_vars < 0 or declared_clauses < 0:
                raise DimacsError("header counts must be non-negative", lineno, raw)
            header_seen = True
            cnf.nvars = declared_vars
            continue

        if not header_seen:
            raise DimacsError(
                "clause data before 'p cnf' header", lineno, raw
            )

        # A line of integers; tokens accumulate into clauses until a 0.
        col = 0
        for tok in line.split():
            idx = raw.find(tok, col)
            col = idx + len(tok) if idx >= 0 else col
            try:
                val = int(tok)
            except ValueError:
                raise DimacsError(
                    f"expected integer literal, got {tok!r}", lineno, raw,
                    col=max(0, idx),
                )
            if val == 0:
                cnf.add_clause(cur)  # add_clause([]) yields a legal empty (UNSAT) clause
                cur = []
                cur_started_line = 0
            else:
                if not cur:
                    cur_started_line = lineno
                cur.append(val)

    if cur:
        raise DimacsError(
            "last clause is missing its terminating 0", cur_started_line or len(lines),
            lines[cur_started_line - 1] if cur_started_line else "",
        )

    if declared_clauses is not None and cnf.nclauses != declared_clauses:
        # Not fatal — many real files miscount — but worth surfacing.
        cnf._header_clause_mismatch = (declared_clauses, cnf.nclauses)  # type: ignore[attr-defined]
    if declared_vars is not None and cnf.nvars < declared_vars:
        cnf.nvars = declared_vars
    return cnf
