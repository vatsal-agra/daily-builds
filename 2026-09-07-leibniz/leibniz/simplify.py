"""Full bottom-up canonicalization.

The smart constructors in expr.py (add/mul/pow_/func_) already fold and
combine as expressions are *built*. ``simplify`` rebuilds an existing tree
bottom-up through those same smart constructors, which guarantees a
canonical form regardless of how the tree was assembled (parsed, built via
raw node construction in a test, produced by substitution, etc.) — after
simplify(), two mathematically-equal-by-construction expressions are equal
as Python objects (``==``), which the rest of the package relies on.
"""

from __future__ import annotations

from .expr import Add, Constant, Expr, Func, Imaginary, Mul, Num, Pow, Symbol, add, func_, mul, pow_


def simplify(e: Expr) -> Expr:
    if isinstance(e, (Num, Symbol, Constant, Imaginary)):
        return e
    if isinstance(e, Func):
        return func_(e.name, simplify(e.arg))
    if isinstance(e, Pow):
        return pow_(simplify(e.base), simplify(e.exp))
    if isinstance(e, Add):
        return add(*[simplify(a) for a in e.args])
    if isinstance(e, Mul):
        return mul(*[simplify(a) for a in e.args])
    raise TypeError(type(e))


def equal(a: Expr, b: Expr) -> bool:
    """Structural equality after simplification -- the CAS's notion of
    'these two expressions are the same', used by the test suite and by the
    integrator's self-check."""
    return simplify(a) == simplify(b)
