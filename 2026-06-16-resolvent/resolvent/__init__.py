"""Resolvent — a from-scratch CDCL SAT solver in pure Python."""

from .cnf import CNF, parse_dimacs, DimacsError
from .solver import Solver, Stats

__all__ = ["CNF", "parse_dimacs", "DimacsError", "Solver", "Stats", "solve"]


def solve(cnf, **kw):
    """Convenience: solve a CNF, return (sat: bool, model: list[int] | None, stats)."""
    s = Solver(cnf, **kw)
    sat = s.solve()
    return sat, (s.model() if sat else None), s.stats
