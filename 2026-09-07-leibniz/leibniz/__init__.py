"""Leibniz -- a computer algebra system built from scratch."""

from .diff import diff
from .expr import E, I, PI, Expr, Num, Symbol, evalf, free_symbols, subs
from .integrate import CannotIntegrate, integrate
from .parser import ParseError, parse, parse_equation
from .polynomial import NotPolynomial, expand, factor
from .render import to_latex, to_str
from .simplify import equal, simplify
from .solve import LinearSystemError, SolveError, solve, solve_linear_system, solve_quadratic

__all__ = [
    "E", "I", "PI", "Expr", "Num", "Symbol",
    "CannotIntegrate", "LinearSystemError", "NotPolynomial", "ParseError", "SolveError",
    "diff", "equal", "evalf", "expand", "factor", "free_symbols", "integrate",
    "parse", "parse_equation", "simplify", "solve", "solve_linear_system",
    "solve_quadratic", "subs", "to_latex", "to_str",
]
