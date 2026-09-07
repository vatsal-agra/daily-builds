"""Rule-based symbolic integration.

Not a full decision procedure (no Risch algorithm) -- a deliberately scoped
table of rules: linearity, the power rule (incl. x**-1 -> ln|x|), the
standard sin/cos/exp/ln table with an affine argument (a*x+b, covering the
plain-x case as a=1, b=0), an exponential-base rule (c**(a*x+b)), and
tabular integration by parts for polynomial * {exp, sin, cos} products.
Anything outside this pattern set raises CannotIntegrate with a clear
message -- never a silent wrong or partial answer.
"""

from __future__ import annotations

from fractions import Fraction

from .diff import diff
from .expr import Add, Expr, Func, Mul, Num, Pow, Symbol, add, free_symbols, func_, is_zero, mul, pow_
from .render import Steps
from .simplify import simplify


class CannotIntegrate(Exception):
    pass


def integrate(e: Expr, var: str, steps: Steps | None = None) -> Expr:
    result = simplify(_integrate(simplify(e), var))
    if steps is not None:
        steps.add(f"integral d{var}", result)
    return result


def contains_var(e: Expr, var: str) -> bool:
    return var in free_symbols(e)


def _integrate(e: Expr, var: str) -> Expr:
    if not contains_var(e, var):
        return e * Symbol(var)

    if isinstance(e, Add):
        return add(*[_integrate(t, var) for t in e.args])

    if isinstance(e, Mul):
        const_factors, var_factors = [], []
        for f in e.args:
            (var_factors if contains_var(f, var) else const_factors).append(f)
        const = mul(*const_factors) if const_factors else Num(1)
        if len(var_factors) == 1:
            return mul(const, _integrate(var_factors[0], var))
        return mul(const, _integrate_product(var_factors, var))

    if isinstance(e, Symbol) and e.name == var:
        return pow_(e, Num(2)) / Num(2)

    if isinstance(e, Pow):
        return _integrate_pow(e, var)

    if isinstance(e, Func):
        return _integrate_func(e, var)

    raise CannotIntegrate(f"no integration rule matches {e}")


def _integrate_pow(e: Pow, var: str) -> Expr:
    base_has_var = contains_var(e.base, var)
    exp_has_var = contains_var(e.exp, var)

    if base_has_var and not exp_has_var:
        aff = _affine_coeffs(e.base, var)
        if aff is not None:
            a, b = aff
            n = e.exp
            if isinstance(n, Num) and n.value == -1:
                return func_("ln", func_("abs", e.base)) / a
            n1 = n + Num(1)
            return pow_(e.base, n1) / (a * n1)

    if exp_has_var and not base_has_var:
        aff = _affine_coeffs(e.exp, var)
        if aff is not None:
            a, b = aff
            return e / (a * func_("ln", e.base))

    raise CannotIntegrate(f"no rule for {e}")


def _integrate_func(e: Func, var: str) -> Expr:
    aff = _affine_coeffs(e.arg, var)
    if aff is None:
        raise CannotIntegrate(f"no rule for {e} (argument is not affine in {var})")
    a, b = aff
    u = e.arg
    if e.name == "sin":
        return Num(-1) * func_("cos", u) / a
    if e.name == "cos":
        return func_("sin", u) / a
    if e.name == "exp":
        return e / a
    if e.name == "ln":
        return (u * (func_("ln", u) - Num(1))) / a
    if e.name == "tan":
        return Num(-1) * func_("ln", func_("abs", func_("cos", u))) / a
    if e.name == "sqrt":
        return Num(2) * pow_(u, Num(Fraction(3, 2))) / (Num(3) * a)
    raise CannotIntegrate(f"no rule for {e.name}(...)")


def _integrate_product(factors: list, var: str) -> Expr:
    poly_factor, other_factor = None, None
    for f in factors:
        if _is_polynomial_in(f, var):
            poly_factor = f if poly_factor is None else mul(poly_factor, f)
        else:
            if other_factor is not None:
                raise CannotIntegrate(f"cannot integrate product {factors}")
            other_factor = f

    if poly_factor is None or other_factor is None:
        raise CannotIntegrate(f"cannot integrate product {factors}")
    if not (isinstance(other_factor, Func) and other_factor.name in ("exp", "sin", "cos")):
        raise CannotIntegrate(f"cannot integrate product {factors}: no by-parts rule applies")
    if _affine_coeffs(other_factor.arg, var) is None:
        raise CannotIntegrate("integration by parts here needs an affine argument")

    return _tabular_by_parts(poly_factor, other_factor, var)


def _is_polynomial_in(f: Expr, var: str) -> bool:
    from .polynomial import NotPolynomial, poly_coeffs

    try:
        poly_coeffs(f, var)
        return True
    except NotPolynomial:
        return False


def _tabular_by_parts(poly: Expr, other: Expr, var: str) -> Expr:
    """Classic tabular integration by parts: successive derivatives of the
    polynomial factor against successive antiderivatives of the other
    factor, alternating sign. Always terminates because a polynomial's
    derivative chain reaches exactly 0 after (degree + 1) steps."""
    u = poly
    v = _integrate(other, var)
    sign = 1
    result = Num(0)
    for _ in range(64):
        result = result + mul(Num(sign), mul(u, v))
        u_next = simplify(diff(u, var))
        if is_zero(u_next):
            return result
        u = u_next
        v = _integrate(v, var)
        sign = -sign
    raise CannotIntegrate("polynomial degree too large for tabular integration by parts")


def _affine_coeffs(expr: Expr, var: str):
    """If expr == a*var + b for some var-free a (a != 0) and b, return
    (a, b) as Expr; else None."""
    expr = simplify(expr)
    terms = expr.args if isinstance(expr, Add) else (expr,)
    a_terms, b_terms = [], []
    for t in terms:
        if not contains_var(t, var):
            b_terms.append(t)
            continue
        if isinstance(t, Symbol) and t.name == var:
            a_terms.append(Num(1))
            continue
        if isinstance(t, Mul):
            var_count = 0
            coeff_parts = []
            for f in t.args:
                if isinstance(f, Symbol) and f.name == var:
                    var_count += 1
                elif not contains_var(f, var):
                    coeff_parts.append(f)
                else:
                    return None
            if var_count != 1:
                return None
            a_terms.append(mul(*coeff_parts) if coeff_parts else Num(1))
            continue
        return None
    a = add(*a_terms) if a_terms else Num(0)
    b = add(*b_terms) if b_terms else Num(0)
    if is_zero(simplify(a)):
        return None
    return a, b
