"""CNF formula model + DIMACS I/O.

A literal is a nonzero int: variable `v` (1..n) appears as `+v` (positive) or
`-v` (negative). A clause is a list of literals (a disjunction). A `CNF` is a
conjunction of clauses over `num_vars` variables.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import List, Iterable


@dataclass
class CNF:
    num_vars: int = 0
    clauses: List[List[int]] = field(default_factory=list)
    # optional comment lines (without the leading 'c ')
    comments: List[str] = field(default_factory=list)

    def add_clause(self, lits: Iterable[int]) -> None:
        cl = [int(x) for x in lits]
        for l in cl:
            if l == 0:
                raise ValueError("0 is not a valid literal")
            v = abs(l)
            if v > self.num_vars:
                self.num_vars = v
        self.clauses.append(cl)

    def new_var(self) -> int:
        self.num_vars += 1
        return self.num_vars

    # ---- DIMACS ----------------------------------------------------------
    def to_dimacs(self) -> str:
        out = []
        for c in self.comments:
            out.append(f"c {c}")
        out.append(f"p cnf {self.num_vars} {len(self.clauses)}")
        for cl in self.clauses:
            out.append(" ".join(str(l) for l in cl) + " 0")
        return "\n".join(out) + "\n"

    @staticmethod
    def from_dimacs(text: str) -> "CNF":
        cnf = CNF()
        declared_vars = None
        declared_clauses = None
        tokens: List[int] = []
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("c"):
                cnf.comments.append(line[1:].strip())
                continue
            if line.startswith("p"):
                parts = line.split()
                # p cnf <vars> <clauses>
                if len(parts) >= 4 and parts[1] == "cnf":
                    try:
                        declared_vars = int(parts[2])
                        declared_clauses = int(parts[3])
                    except ValueError:
                        raise ValueError(
                            f"line {lineno}: malformed problem line: {line!r}")
                continue
            if line.startswith("%"):  # some DIMACS files end with a % line
                break
            for tok in line.split():
                try:
                    tokens.append(int(tok))
                except ValueError:
                    raise ValueError(
                        f"line {lineno}: expected an integer literal, got "
                        f"{tok!r} (DIMACS clauses are space-separated ints "
                        f"terminated by 0)")
        # tokens are clauses separated by 0
        cur: List[int] = []
        for t in tokens:
            if t == 0:
                cnf.add_clause(cur)
                cur = []
            else:
                cur.append(t)
        if cur:
            # trailing clause without terminating 0 — accept it
            cnf.add_clause(cur)
        if declared_vars is not None:
            cnf.num_vars = max(cnf.num_vars, declared_vars)
        if declared_clauses is not None and declared_clauses != len(cnf.clauses):
            # not fatal, but worth surfacing on stderr in CLI usage
            cnf.comments.append(
                f"(note: header declared {declared_clauses} clauses, "
                f"read {len(cnf.clauses)})"
            )
        return cnf

    # ---- semantics -------------------------------------------------------
    def is_satisfied_by(self, model: dict) -> bool:
        """`model` maps var -> bool. Returns True iff every clause has a true literal."""
        for cl in self.clauses:
            ok = False
            for l in cl:
                v = abs(l)
                if v not in model:
                    # treat missing as either polarity is allowed -> clause
                    # could be satisfied; but for a *complete* check we require
                    # all vars present. Be strict: missing var = not satisfied
                    # unless another literal already satisfies the clause.
                    continue
                if (l > 0) == model[v]:
                    ok = True
                    break
            if not ok:
                return False
        return True


def read_dimacs_file(path: str) -> CNF:
    if path == "-":
        return CNF.from_dimacs(sys.stdin.read())
    with open(path, "r") as f:
        return CNF.from_dimacs(f.read())
