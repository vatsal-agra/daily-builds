"""AllSAT / #SAT by blocking clauses.

Enumerate (or count) every satisfying assignment of a CNF by repeatedly solving
and adding the negation of each model found as a blocking clause, until the
formula becomes UNSAT.  Exact, and for small instances cross-checkable against
the brute-force counter.
"""

from __future__ import annotations

from typing import List, Iterator
from .cnf import CNF
from .solver import Solver, SAT


def all_models(cnf: CNF, limit: int | None = None) -> Iterator[List[int]]:
    """Yield every satisfying assignment (as signed-literal lists over all vars)."""
    n = cnf.num_vars
    work = cnf.copy()
    found = 0
    while True:
        s = Solver(work)
        if s.solve() != SAT:
            return
        model = [s.value[v] for v in range(1, n + 1)]
        lits = [(v if model[v - 1] else -v) for v in range(1, n + 1)]
        yield lits
        found += 1
        if limit is not None and found >= limit:
            return
        # block this exact assignment
        work.add_clause([-(v if model[v - 1] else -v) for v in range(1, n + 1)])


def count_models(cnf: CNF, limit: int | None = None) -> int:
    total = 0
    for _ in all_models(cnf, limit):
        total += 1
    return total
