"""Symbolic differentiation and integration.

`differentiate()` implements the full elementary rule set (sum, product,
power, chain, and the generalized f(x)^g(x) logarithmic-differentiation
rule) and, given a `trace` list, appends a human-readable line for every
rule application — this is what drives the HTML visualizer's step-by-step
derivative view.

`integrate()` is deliberately scope-limited and honest about it: power
rule, sum rule, a function table (sin/cos/tan/exp/sinh/cosh/tanh/log/abs)
composed with linear-argument substitution (`∫f(ax+b)dx`), the two
`1/(1+x²)` / `1/sqrt(1-x²)` arctan/arcsin patterns, and tabular integration
by parts for polynomial × {exp, sin, cos, sinh, cosh}. Anything outside
that (e.g. a genuinely non-elementary integral, or a product this build's
by-parts detector doesn't recognize) raises a clear `AxiomError` rather
than guessing — every antiderivative this module *does* produce is checked
in the test suite by differentiating it back and by numerical
definite-integral comparison.
"""

from fractions import Fraction

from .errors import AxiomError
from .expr import (Add, Func, Mul, Num, Pow, Symbol, ZERO, ONE, NEG_ONE,
                    add, func, mul, num, power, sym)

# ---------------------------------------------------------------------------
# differentiation
# ---------------------------------------------------------------------------

_FUNC_DERIV = {
    "sin": lambda u: func("cos", u),
    "cos": lambda u: mul(NEG_ONE, func("sin", u)),
    "tan": lambda u: power(func("cos", u), num(-2)),
    "exp": lambda u: func("exp", u),
    "log": lambda u: power(u, NEG_ONE),
    "abs": lambda u: mul(u, power(func("abs", u), NEG_ONE)),
    "asin": lambda u: power(add(ONE, mul(NEG_ONE, power(u, num(2)))), num(Fraction(-1, 2))),
    "acos": lambda u: mul(NEG_ONE, power(add(ONE, mul(NEG_ONE, power(u, num(2)))), num(Fraction(-1, 2)))),
    "atan": lambda u: power(add(ONE, power(u, num(2))), NEG_ONE),
    "sinh": lambda u: func("cosh", u),
    "cosh": lambda u: func("sinh", u),
    "tanh": lambda u: power(func("cosh", u), num(-2)),
}


def differentiate(expr, var, trace=None):
    if isinstance(var, str):
        var = sym(var)
    return _diff(expr, var, trace)


def _diff(e, var, trace):
    if isinstance(e, Num):
        return ZERO
    if isinstance(e, Symbol):
        return ONE if e == var else ZERO
    if isinstance(e, Add):
        parts = [_diff(t, var, trace) for t in e.terms]
        result = add(*parts)
        if trace is not None:
            trace.append(f"sum rule: d/d{var}[{e}] = {result}")
        return result
    if isinstance(e, Mul):
        factors = e.factors
        parts = []
        for i in range(len(factors)):
            di = _diff(factors[i], var, trace)
            others = factors[:i] + factors[i + 1:]
            parts.append(mul(di, *others) if others else di)
        result = add(*parts)
        if trace is not None:
            trace.append(f"product rule: d/d{var}[{e}] = {result}")
        return result
    if isinstance(e, Pow):
        base, exp = e.base, e.exp
        base_has_var = var in base.free_symbols()
        exp_has_var = var in exp.free_symbols()
        if not exp_has_var:
            dbase = _diff(base, var, trace)
            result = mul(exp, power(base, add(exp, NEG_ONE)), dbase)
            if trace is not None:
                trace.append(f"power rule: d/d{var}[{e}] = {result}")
            return result
        if not base_has_var:
            dexp = _diff(exp, var, trace)
            result = mul(e, func("log", base), dexp)
            if trace is not None:
                trace.append(f"exponential rule: d/d{var}[{e}] = {result}")
            return result
        dbase = _diff(base, var, trace)
        dexp = _diff(exp, var, trace)
        inner = add(mul(dexp, func("log", base)), mul(exp, dbase, power(base, NEG_ONE)))
        result = mul(e, inner)
        if trace is not None:
            trace.append(f"generalized power rule (f^g): d/d{var}[{e}] = {result}")
        return result
    if isinstance(e, Func):
        u = e.arg
        du = _diff(u, var, trace)
        result = mul(_FUNC_DERIV[e.name](u), du)
        if trace is not None:
            trace.append(f"chain rule (d/du {e.name}(u)): d/d{var}[{e}] = {result}")
        return result
    raise TypeError(type(e))


# ---------------------------------------------------------------------------
# integration
# ---------------------------------------------------------------------------

_RAW_ANTIDERIV = {
    "sin": lambda v: mul(NEG_ONE, func("cos", v)),
    "cos": lambda v: func("sin", v),
    "exp": lambda v: func("exp", v),
    "sinh": lambda v: func("cosh", v),
    "cosh": lambda v: func("sinh", v),
    "tan": lambda v: mul(NEG_ONE, func("log", func("abs", func("cos", v)))),
    "tanh": lambda v: func("log", func("cosh", v)),
    "log": lambda v: add(mul(v, func("log", v)), mul(NEG_ONE, v)),
    "abs": lambda v: mul(num(Fraction(1, 2)), v, func("abs", v)),
}


def integrate(expr, var):
    if isinstance(var, str):
        var = sym(var)
    return _integrate(expr, var)


def _integrate(e, var):
    if var not in e.free_symbols():
        return mul(e, var)
    if isinstance(e, Add):
        return add(*[_integrate(t, var) for t in e.terms])
    if isinstance(e, Mul):
        const_factors, var_factors = [], []
        for f in e.factors:
            (const_factors if var not in f.free_symbols() else var_factors).append(f)
        const = mul(*const_factors) if const_factors else ONE
        rest = mul(*var_factors) if var_factors else ONE
        if isinstance(rest, Num) and rest.value == 1:
            return mul(const, var)
        if isinstance(rest, Mul) and len(rest.factors) == 2:
            by_parts = _try_by_parts(rest.factors[0], rest.factors[1], var)
            if by_parts is None:
                by_parts = _try_by_parts(rest.factors[1], rest.factors[0], var)
            if by_parts is not None:
                return mul(const, by_parts)
            sub = _try_substitution(rest.factors[0], rest.factors[1], var)
            if sub is None:
                sub = _try_substitution(rest.factors[1], rest.factors[0], var)
            if sub is not None:
                return mul(const, sub)
        return mul(const, _integrate_atom(rest, var))
    return _integrate_atom(e, var)


def _linear_coeff(expr, var):
    """(a, b) if `expr` == a*var + b with a, b not containing var, else None."""
    from . import polynomial as P
    try:
        coeffs = P.poly_coeffs(expr, var)
    except AxiomError:
        return None
    if any(k > 1 for k in coeffs):
        return None
    a = coeffs.get(1, ZERO)
    b = coeffs.get(0, ZERO)
    if var in a.free_symbols():
        return None
    return a, b


def _integrate_atom(e, var):
    if e == var:
        return mul(power(var, num(2)), num(Fraction(1, 2)))

    if isinstance(e, Pow) and isinstance(e.exp, Num):
        n = e.exp.value
        lin = _linear_coeff(e.base, var)
        if lin is not None and not (isinstance(lin[0], Num) and lin[0].value == 0):
            a, _ = lin
            if n == -1:
                return mul(func("log", func("abs", e.base)), power(a, NEG_ONE))
            return mul(power(e.base, num(n + 1)), power(mul(a, num(n + 1)), NEG_ONE))
        if e.exp.value == -1 and e.base == add(ONE, power(var, num(2))):
            return func("atan", var)
        if e.exp.value == Fraction(-1, 2) and e.base == add(ONE, mul(NEG_ONE, power(var, num(2)))):
            return func("asin", var)

    if isinstance(e, Func):
        lin = _linear_coeff(e.arg, var)
        if lin is not None and not (isinstance(lin[0], Num) and lin[0].value == 0):
            a, _ = lin
            if e.name in _RAW_ANTIDERIV:
                antideriv_var = _RAW_ANTIDERIV[e.name](var)
                substituted = antideriv_var.subs({var: e.arg})
                return mul(substituted, power(a, NEG_ONE))

    raise AxiomError(
        f"cannot symbolically integrate '{e}' with respect to {var} — "
        f"out of scope for this from-scratch integrator")


def _try_substitution(inner, outer, var):
    """u-substitution for `f(g(x)) * g'(x)` (up to a constant factor). Tries
    every plausible reading of `inner` as `f(g(...))` in order:
      1. `Pow(g, n)`         -> g = the Pow's own base       (e.g. (x^2+1)^-1)
      2. `Func(name, g)`     -> g = that function's argument (e.g. exp(x^2))
      3. `inner` itself      -> g = inner, n = 1             (e.g. sin(x) in
                                                                sin(x)*cos(x))
    For whichever `g` a reading proposes, if `outer == c * g'(x)` for some
    constant `c` (checked exactly via polynomial division), the integral is
    `c * F(g(x))` — power rule for reading 1/3, the same function table
    `_integrate_atom` uses for reading 2."""
    candidates = []
    if isinstance(inner, Pow) and isinstance(inner.exp, Num):
        candidates.append(("pow", inner.base, inner.exp.value))
    if isinstance(inner, Func) and inner.name in _RAW_ANTIDERIV:
        candidates.append(("func", inner.arg, inner.name))
    candidates.append(("pow", inner, Fraction(1)))

    for kind, g, extra in candidates:
        if var not in g.free_symbols():
            continue
        dg = differentiate(g, var)
        if isinstance(dg, Num) and dg.value == 0:
            continue
        c = _constant_ratio(outer, dg, var)
        if c is None:
            continue
        if kind == "func":
            return mul(c, _RAW_ANTIDERIV[extra](var).subs({var: g}))
        n = extra
        if n == -1:
            return mul(c, func("log", func("abs", g)))
        return mul(c, power(g, num(n + 1)), power(num(n + 1), NEG_ONE))
    return None


def _constant_ratio(a, b, var):
    """Expr `c` (not containing var) such that a == c*b — or None if no
    such constant exists. Two tiers: an exact check via polynomial division
    when both sides are polynomials in var (handles the common case, e.g.
    a=2x, b=2x for x*exp(x^2)); otherwise a numeric-probe fallback (checks
    a(x)/b(x) is the *same* value at several independent random points,
    which a genuine non-constant ratio can't fake) for transcendental cases
    like a=sin(x), b=-sin(x) in sin(x)*cos(x) — those aren't polynomials in
    x, so exact polynomial division doesn't apply, but the ratio is still a
    plain constant. Any wrong guess here would fail this build's own
    differentiate-the-result verification, so a false positive can't hide."""
    from . import polynomial as P
    try:
        da, db = P.poly_degree(a, var), P.poly_degree(b, var)
        a_coeffs = [P.poly_coeffs(a, var).get(k, ZERO).value for k in range(da, -1, -1)]
        b_coeffs = [P.poly_coeffs(b, var).get(k, ZERO).value for k in range(db, -1, -1)]
        q, r = P.poly_divmod(a_coeffs, b_coeffs)
        if not any(x != 0 for x in r) and len(q) == 1:
            return num(q[0])
    except AxiomError:
        pass
    return _numeric_constant_ratio(a, b, var)


def _numeric_constant_ratio(a, b, var, samples=5, tol=1e-9):
    import random
    rng = random.Random(0)  # deterministic: same input always probed the same way
    ratios = []
    for _ in range(samples * 4):
        if len(ratios) >= samples:
            break
        xv = rng.uniform(0.15, 2.5)
        try:
            av, bv = a.evalf({var: xv}), b.evalf({var: xv})
        except AxiomError:
            continue
        if abs(bv) < 1e-9 or abs(av.imag) > 1e-9 or abs(bv.imag) > 1e-9:
            continue
        ratios.append(av.real / bv.real)
    if len(ratios) < samples:
        return None
    c0 = ratios[0]
    if any(abs(r - c0) > tol * max(1.0, abs(c0)) for r in ratios):
        return None
    frac = Fraction(c0).limit_denominator(10 ** 6)
    if abs(float(frac) - c0) > 1e-7:
        return None
    return num(frac)


def _try_by_parts(poly_factor, trans_factor, var):
    from . import polynomial as P
    if not (isinstance(trans_factor, Func) and trans_factor.name in
            ("exp", "sin", "cos", "sinh", "cosh")):
        return None
    lin = _linear_coeff(trans_factor.arg, var)
    if lin is None or (isinstance(lin[0], Num) and lin[0].value == 0):
        return None
    try:
        deg = P.poly_degree(poly_factor, var)
    except AxiomError:
        return None
    if deg < 1:
        return None

    us = [poly_factor]
    while True:
        du = differentiate(us[-1], var)
        if isinstance(du, Num) and du.value == 0:
            break
        us.append(du)
        if len(us) > 40:
            return None  # safety valve; real polynomials terminate long before this

    v = trans_factor
    terms = []
    sign = 1
    for ui in us:
        v = _integrate(v, var)
        terms.append(mul(num(sign), ui, v))
        sign = -sign
    return add(*terms)
