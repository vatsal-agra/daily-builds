"""Symbolic differentiation."""

from __future__ import annotations

from .expr import Add, Constant, Expr, Func, Imaginary, Mul, Num, Pow, Symbol, func_, is_zero, pow_
from .render import Steps


def diff(e: Expr, var: str, steps: Steps | None = None) -> Expr:
    """d(e)/d(var). `var` is a symbol name (e.g. "x")."""
    result = _diff(e, var)
    if steps is not None:
        steps.add(f"d/d{var}", result)
    return result


def _diff(e: Expr, var: str) -> Expr:
    if isinstance(e, Num):
        return Num(0)
    if isinstance(e, (Constant, Imaginary)):
        return Num(0)
    if isinstance(e, Symbol):
        return Num(1) if e.name == var else Num(0)
    if isinstance(e, Add):
        return sum((_diff(a, var) for a in e.args), Num(0))
    if isinstance(e, Mul):
        return _diff_mul(e, var)
    if isinstance(e, Pow):
        return _diff_pow(e, var)
    if isinstance(e, Func):
        return _diff_func(e, var)
    raise TypeError(type(e))


def _diff_mul(e: Mul, var: str) -> Expr:
    # generalized product rule: d(f1*f2*...*fn) = sum_i d(fi) * prod_{j!=i} fj
    total = Num(0)
    for i, fi in enumerate(e.args):
        term = _diff(fi, var)
        for j, fj in enumerate(e.args):
            if j != i:
                term = term * fj
        total = total + term
    return total


def _diff_pow(e: Pow, var: str) -> Expr:
    base, exp = e.base, e.exp
    dbase = _diff(base, var)
    dexp = _diff(exp, var)

    if is_zero(dexp):
        # power rule (+ chain rule): d(f^c) = c * f^(c-1) * d(f)
        if is_zero(dbase):
            return Num(0)
        return exp * pow_(base, exp - Num(1)) * dbase

    if is_zero(dbase):
        # exponential rule (+ chain rule): d(c^g) = c^g * ln(c) * d(g)
        return e * func_("ln", base) * dexp

    # general case, both f and g depend on var: logarithmic differentiation
    # d(f^g) = f^g * ( d(g)*ln(f) + g * d(f)/f )
    return e * (dexp * func_("ln", base) + exp * dbase / base)


def _diff_func(e: Func, var: str) -> Expr:
    u = e.arg
    du = _diff(u, var)
    if is_zero(du):
        return Num(0)
    if e.name == "sin":
        return func_("cos", u) * du
    if e.name == "cos":
        return Num(-1) * func_("sin", u) * du
    if e.name == "tan":
        return du / pow_(func_("cos", u), Num(2))
    if e.name == "exp":
        return e * du
    if e.name == "ln":
        return du / u
    if e.name == "sqrt":
        return du / (Num(2) * e)
    if e.name == "abs":
        return (u / e) * du
    raise TypeError(e.name)
