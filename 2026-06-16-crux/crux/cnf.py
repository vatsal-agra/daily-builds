"""CNF representation and DIMACS I/O for Crux.

Literals use the standard DIMACS integer convention everywhere a human-facing
value is needed: a positive integer ``v`` means variable ``v`` is true, ``-v``
means it is false. Variables are 1-indexed; ``0`` is never a valid literal.

A :class:`CNF` is just a list of clauses, each clause a list of integer literals,
plus a record of how many variables exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence


class DimacsError(ValueError):
    """Raised when a DIMACS stream is malformed, with line context."""


@dataclass
class CNF:
    """A formula in conjunctive normal form.

    Attributes:
        nvars: highest variable index declared/used (variables are 1..nvars).
        clauses: list of clauses; each clause is a list of non-zero int literals.
    """

    nvars: int = 0
    clauses: List[List[int]] = field(default_factory=list)

    # -- construction -----------------------------------------------------
    def add_clause(self, lits: Iterable[int]) -> "CNF":
        """Add a clause (list of literals). Updates ``nvars`` automatically.

        A literal of ``0`` is rejected (0 terminates clauses in DIMACS and is
        never a real literal). Duplicate literals within the clause are kept as
        given except exact duplicates are collapsed; a clause containing both a
        literal and its negation is a tautology and is dropped.
        """
        clause: List[int] = []
        seen = set()
        for lit in lits:
            lit = int(lit)
            if lit == 0:
                raise ValueError("0 is not a valid literal")
            if -lit in seen:
                # tautological clause (x or not x) -- always satisfied, drop it
                return self
            if lit in seen:
                continue
            seen.add(lit)
            clause.append(lit)
            v = abs(lit)
            if v > self.nvars:
                self.nvars = v
        self.clauses.append(clause)
        return self

    def extend(self, clauses: Iterable[Sequence[int]]) -> "CNF":
        for c in clauses:
            self.add_clause(c)
        return self

    # -- introspection ----------------------------------------------------
    @property
    def nclauses(self) -> int:
        return len(self.clauses)

    def variables(self) -> List[int]:
        vs = set()
        for c in self.clauses:
            for lit in c:
                vs.add(abs(lit))
        return sorted(vs)

    def is_satisfied_by(self, model) -> bool:
        """True if ``model`` satisfies every clause.

        ``model`` may be a dict {var: bool}, a set of true literals, or a list of
        signed literals (DIMACS style). Missing variables are treated as
        unassigned and make any clause relying on them unsatisfied unless another
        literal already satisfies it.
        """
        truth = _model_to_truth(model)
        for c in self.clauses:
            if not any(
                (truth.get(abs(lit)) is True) == (lit > 0)
                and truth.get(abs(lit)) is not None
                for lit in c
            ):
                return False
        return True

    def unsatisfied_clauses(self, model) -> List[List[int]]:
        """Return clauses not satisfied by ``model`` (useful for debugging)."""
        truth = _model_to_truth(model)
        bad = []
        for c in self.clauses:
            ok = any(
                truth.get(abs(lit)) is not None
                and (truth.get(abs(lit)) is True) == (lit > 0)
                for lit in c
            )
            if not ok:
                bad.append(c)
        return bad

    def copy(self) -> "CNF":
        return CNF(self.nvars, [list(c) for c in self.clauses])

    # -- DIMACS -----------------------------------------------------------
    def to_dimacs(self) -> str:
        lines = [f"p cnf {self.nvars} {self.nclauses}"]
        for c in self.clauses:
            lines.append(" ".join(str(x) for x in c) + " 0")
        return "\n".join(lines) + "\n"


def _model_to_truth(model) -> dict:
    """Normalise a model into {var: bool|None}."""
    if isinstance(model, dict):
        # keys may be ints (vars). Values bool.
        return {int(k): bool(v) for k, v in model.items()}
    truth: dict = {}
    for lit in model:
        lit = int(lit)
        if lit == 0:
            continue
        truth[abs(lit)] = lit > 0
    return truth


def parse_dimacs(text: str) -> CNF:
    """Parse a DIMACS CNF string into a :class:`CNF`.

    Tolerant of: leading ``c`` comment lines, blank lines, clauses split across
    multiple lines (terminated by ``0``), and extra whitespace. The ``p cnf V C``
    header is honoured for the declared variable count but the parser does not
    fail if the actual counts differ (many real files lie); it raises only on
    genuinely malformed tokens.
    """
    cnf = CNF()
    declared_vars = None
    current: List[int] = []
    saw_header = False
    in_clause_started = False

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line[0] == "c":
            continue
        if line[0] == "p":
            parts = line.split()
            if len(parts) < 4 or parts[1] != "cnf":
                raise DimacsError(
                    f"line {lineno}: bad header {line!r} (expected 'p cnf V C')"
                )
            try:
                declared_vars = int(parts[2])
                int(parts[3])  # clause count, validated but not enforced
            except ValueError:
                raise DimacsError(f"line {lineno}: header counts must be integers")
            saw_header = True
            continue
        if line[0] == "%":
            # some DIMACS files end with a '%' / '0' trailer; stop reading.
            break
        for tok in line.split():
            try:
                lit = int(tok)
            except ValueError:
                raise DimacsError(f"line {lineno}: invalid literal token {tok!r}")
            if lit == 0:
                cnf.add_clause(current)
                current = []
                in_clause_started = False
            else:
                current.append(lit)
                in_clause_started = True

    if in_clause_started and current:
        # A trailing clause without a terminating 0 -- accept it but note it.
        cnf.add_clause(current)

    if declared_vars is not None and declared_vars > cnf.nvars:
        cnf.nvars = declared_vars
    if not saw_header and not cnf.clauses:
        raise DimacsError("no 'p cnf' header and no clauses found")
    return cnf


def parse_dimacs_file(path: str) -> CNF:
    with open(path, "r", encoding="utf-8") as fh:
        return parse_dimacs(fh.read())
