"""Axiom — a from-scratch computer algebra system.

Pure Python 3 stdlib only. See PLAN.md / README.md at the project root.
"""

from .errors import AxiomError, DomainError, ParseError
from .expr import (Expr, Num, Symbol, Add, Mul, Pow, Func, sym, num, add, mul, power, func,
                    RESERVED_CONSTANT_NAMES)
from .parser import parse
from .simplify import simplify
from .calculus import differentiate, integrate
from .solve import solve
from .polynomial import expand, factor, poly_gcd
from .matrix import Matrix
from .latex import to_latex

__all__ = [
    "AxiomError", "DomainError", "ParseError",
    "Expr", "Num", "Symbol", "Add", "Mul", "Pow", "Func",
    "sym", "num", "add", "mul", "power", "func",
    "parse", "simplify", "differentiate", "integrate", "solve",
    "expand", "factor", "poly_gcd", "Matrix", "to_latex", "RESERVED_CONSTANT_NAMES",
]
