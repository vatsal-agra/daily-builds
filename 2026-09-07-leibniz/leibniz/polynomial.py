"""Univariate polynomial helpers: expansion, coefficient extraction,
long division, and factoring via GCD extraction + the rational root
theorem.

A polynomial is represented, when convenient, as a list of `Fraction`
coefficients ``[c0, c1, c2, ...]`` meaning ``c0 + c1*x + c2*x**2 + ...``
(index == degree).
"""

from __future__ import annotations

from fractions import Fraction
from math import gcd

from .expr import Add, Expr, Mul, Num, Pow, Symbol, _distribute_pair, add, free_symbols, mul, pow_
from .render import to_str
from .simplify import simplify


class NotPolynomial(Exception):
    pass


# ---------------------------------------------------------------------------
# expand
# ---------------------------------------------------------------------------

MAX_EXPAND_EXPONENT = 30


def expand(e: Expr) -> Expr:
    """Fully distribute sums over products and non-negative integer powers
    of sums, e.g. (x+1)*(x+2) -> x**2 + 3*x + 2, (x+1)**3 -> ..."""
    return _expand(simplify(e))


def _expand(e: Expr) -> Expr:
    if isinstance(e, (Num, Symbol)):
        return e
    if not isinstance(e, (Add, Mul, Pow)) and not hasattr(e, "arg"):
        return e
    from .expr import Func

    if isinstance(e, Func):
        return simplify(Func(e.name, _expand(e.arg)))
    if isinstance(e, Add):
        return add(*[_expand(a) for a in e.args])
    if isinstance(e, Mul):
        result = Num(1)
        for f in e.args:
            result = _distribute_pair(result, _expand(f))
        return result
    if isinstance(e, Pow):
        base = _expand(e.base)
        if isinstance(e.exp, Num) and e.exp.value.denominator == 1 and e.exp.value >= 0 and isinstance(base, Add):
            n = int(e.exp.value)
            if n > MAX_EXPAND_EXPONENT:
                raise NotPolynomial(f"exponent {n} too large to expand")
            result = Num(1)
            for _ in range(n):
                result = _distribute_pair(result, base)
            return result
        return pow_(base, _expand(e.exp))
    return e


# ---------------------------------------------------------------------------
# coefficient extraction
# ---------------------------------------------------------------------------


def univariate_var(e: Expr) -> str:
    syms = free_symbols(e)
    if not syms:
        raise NotPolynomial(f"{to_str(e)} has no variable to factor (it's just a constant)")
    if len(syms) > 1:
        raise NotPolynomial(f"expected exactly one variable, found {sorted(syms)} in {to_str(e)}")
    return next(iter(syms))


def poly_coeffs(e: Expr, var: str) -> list[Fraction]:
    """Coefficients of e as a polynomial in `var`, low-to-high degree.
    Raises NotPolynomial if e isn't a polynomial in var (e.g. it contains
    sin(x), 1/x, x**(1/2), or a second free variable)."""
    e = expand(e)
    terms = e.args if isinstance(e, Add) else (e,)
    coeffs: dict[int, Fraction] = {}
    for t in terms:
        c, d = _term_coeff_degree(t, var)
        coeffs[d] = coeffs.get(d, Fraction(0)) + c
    maxdeg = max(coeffs) if coeffs else 0
    return [coeffs.get(d, Fraction(0)) for d in range(maxdeg + 1)]


def _term_coeff_degree(t: Expr, var: str):
    if isinstance(t, Num):
        return t.value, 0
    if isinstance(t, Symbol):
        if t.name == var:
            return Fraction(1), 1
        raise NotPolynomial(f"not univariate in {var!r}: found symbol {t.name!r}")
    if isinstance(t, Pow) and isinstance(t.base, Symbol) and t.base.name == var:
        if isinstance(t.exp, Num) and t.exp.value.denominator == 1 and t.exp.value >= 0:
            return Fraction(1), int(t.exp.value)
        raise NotPolynomial(f"non-integer power of {var!r}: {t}")
    if isinstance(t, Mul):
        coeff, degree = Fraction(1), 0
        for f in t.args:
            c, d = _term_coeff_degree(f, var)
            coeff *= c
            degree += d
        return coeff, degree
    raise NotPolynomial(f"not a polynomial term in {var!r}: {t}")


def poly_from_coeffs(coeffs: list[Fraction], var: str) -> Expr:
    x = Symbol(var)
    return add(*[Num(c) * pow_(x, Num(i)) for i, c in enumerate(coeffs)])


def poly_eval(coeffs: list[Fraction], x: Fraction) -> Fraction:
    result = Fraction(0)
    for c in reversed(coeffs):
        result = result * x + c
    return result


# ---------------------------------------------------------------------------
# long division / gcd
# ---------------------------------------------------------------------------


def _strip(c: list[Fraction]) -> list[Fraction]:
    c = list(c)
    while len(c) > 1 and c[-1] == 0:
        c.pop()
    return c


def poly_div(num: list[Fraction], den: list[Fraction]):
    """Return (quotient, remainder) as coefficient lists (low-to-high)."""
    den = _strip(den)
    if all(c == 0 for c in den):
        raise ZeroDivisionError("polynomial division by zero")
    deg_den = len(den) - 1
    remainder = list(num)
    deg_num = len(remainder) - 1
    if deg_num < deg_den:
        return [Fraction(0)], remainder
    quotient = [Fraction(0)] * (deg_num - deg_den + 1)
    for i in range(deg_num - deg_den, -1, -1):
        coeff = remainder[i + deg_den] / den[deg_den]
        quotient[i] = coeff
        for j, dc in enumerate(den):
            remainder[i + j] -= coeff * dc
    return quotient, _strip(remainder)


def poly_gcd(a: list[Fraction], b: list[Fraction]) -> list[Fraction]:
    a, b = _strip(a), _strip(b)
    while not (len(b) == 1 and b[0] == 0):
        _, r = poly_div(a, b)
        a, b = b, _strip(r)
    lead = a[-1]
    return [c / lead for c in a] if lead != 0 else a


def poly_add(a: list[Fraction], b: list[Fraction]) -> list[Fraction]:
    n = max(len(a), len(b))
    a = a + [Fraction(0)] * (n - len(a))
    b = b + [Fraction(0)] * (n - len(b))
    return _strip([x + y for x, y in zip(a, b)])


def poly_mul(a: list[Fraction], b: list[Fraction]) -> list[Fraction]:
    out = [Fraction(0)] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        if x == 0:
            continue
        for j, y in enumerate(b):
            out[i + j] += x * y
    return _strip(out)


# ---------------------------------------------------------------------------
# factoring
# ---------------------------------------------------------------------------


def _rational_root_candidates(coeffs: list[Fraction]) -> list[Fraction]:
    # clear denominators to get an integer polynomial, then apply the
    # rational root theorem: root = +-p/q, p | constant term, q | leading coeff
    lcm_den = 1
    for c in coeffs:
        lcm_den = lcm_den * c.denominator // gcd(lcm_den, c.denominator)
    ints = [int(c * lcm_den) for c in coeffs]
    const, lead = ints[0], ints[-1]
    if const == 0:
        p_divs = [1]
    else:
        p_divs = _divisors(abs(const))
    q_divs = _divisors(abs(lead)) if lead != 0 else [1]
    seen = set()
    candidates = []
    for p in p_divs:
        for q in q_divs:
            for sign in (1, -1):
                r = Fraction(sign * p, q)
                if r not in seen:
                    seen.add(r)
                    candidates.append(r)
    return candidates


def _divisors(n: int) -> list[int]:
    if n == 0:
        return [1]
    out = []
    i = 1
    while i * i <= n:
        if n % i == 0:
            out.append(i)
            out.append(n // i)
        i += 1
    return sorted(set(out))


def factor(e: Expr) -> Expr:
    """Factor a univariate polynomial. Returns a (deliberately unexpanded)
    product expression: Num(scale) * x**k * (a linear or a*x-b factor per
    rational root, grouped by multiplicity) * (exact quadratic-formula
    factors for a degree-2 remainder) * (one leftover irreducible-over-the-
    rationals factor for a degree >= 3 remainder, at most one). Every
    numeric scale contribution (the polynomial's integer content, and the
    denominator cleared out of each rational root to keep factors looking
    like (2*x + 1) rather than (x + 1/2)) is folded into one overall Num,
    never scattered across several. Verify with expand(factor(e)) ==
    expand(e)."""
    simplified = simplify(e)
    if isinstance(simplified, Num) and simplified.value == 0:
        # the zero polynomial factors as 0 regardless of how many (if any)
        # variables it superficially mentions before cancelling out
        return Num(0)

    var = univariate_var(simplified)
    x = Symbol(var)
    coeffs = _strip(poly_coeffs(simplified, var))

    if all(c == 0 for c in coeffs):
        return Num(0)

    # overall rational content: gcd of numerators / lcm of denominators
    lcm_den = 1
    for c in coeffs:
        lcm_den = lcm_den * c.denominator // gcd(lcm_den, c.denominator)
    ints = [int(c * lcm_den) for c in coeffs]
    content = 0
    for v in ints:
        content = gcd(content, abs(v))
    content = content or 1
    overall_scale = Fraction(content, lcm_den)
    coeffs = [c / overall_scale for c in coeffs]  # now integer-valued Fractions

    # factor out x**k for a zero constant term
    k = 0
    while len(coeffs) > 1 and coeffs[0] == 0:
        coeffs.pop(0)
        k += 1

    linear_factors: list[Expr] = []

    # rational-root extraction
    root_mult: dict[Fraction, int] = {}
    while len(coeffs) - 1 >= 1:
        candidates = _rational_root_candidates(coeffs)
        found = None
        for r in candidates:
            if poly_eval(coeffs, r) == 0:
                found = r
                break
        if found is None:
            break
        root_mult[found] = root_mult.get(found, 0) + 1
        coeffs, _ = poly_div(coeffs, [-found, Fraction(1)])
        coeffs = _strip(coeffs)

    for r, mult in root_mult.items():
        p, q = r.numerator, r.denominator
        if q == 1:
            factor_expr = x - Num(p)
        else:
            # display (q*x - p) instead of (x - p/q); compensate the scale
            factor_expr = Num(q) * x - Num(p)
            overall_scale /= Fraction(q) ** mult
        linear_factors.append(pow_(factor_expr, Num(mult)) if mult > 1 else factor_expr)

    remaining_degree = len(coeffs) - 1
    quadratic_factors: list[Expr] = []
    leftover_factor = None
    if remaining_degree == 0:
        # every root was rational; the residual is the leading coefficient
        # of the (content-free) polynomial (monic division never changes it)
        overall_scale *= coeffs[0]
    elif remaining_degree == 2:
        from .solve import solve_quadratic

        a, b, c = coeffs[2], coeffs[1], coeffs[0]
        overall_scale *= a
        for r in solve_quadratic(Num(a), Num(b), Num(c)):
            quadratic_factors.append(x - r)
    else:
        # no more rational roots, degree >= 3: irreducible-over-the-
        # rationals remainder, kept as a single factor as-is
        leftover_factor = poly_from_coeffs(coeffs, var)

    factors_out: list[Expr] = []
    if overall_scale != 1:
        factors_out.append(Num(overall_scale))
    if k > 0:
        factors_out.append(pow_(x, Num(k)) if k > 1 else x)
    factors_out.extend(linear_factors)
    factors_out.extend(quadratic_factors)
    if leftover_factor is not None:
        factors_out.append(leftover_factor)

    if not factors_out:
        return Num(1)
    if len(factors_out) == 1:
        return factors_out[0]
    return Mul(tuple(factors_out))


# ---------------------------------------------------------------------------
# rational-function simplification (bonus, beyond the planned feature list):
# combine a sum of fractions in one variable over a common denominator, then
# cancel their GCD -- e.g. (x^2-1)/(x-1) -> x+1, or 1/x + 1/(x+1) ->
# (2*x+1)/(x^2+x). Best-effort: returns `e` unchanged (never raises) if it
# isn't a rational function of exactly one variable.
# ---------------------------------------------------------------------------


def simplify_rational(e: Expr) -> Expr:
    e = expand(e)
    try:
        var = univariate_var(e)
    except NotPolynomial:
        return e

    terms = e.args if isinstance(e, Add) else (e,)
    parts = []
    for t in terms:
        factors = t.args if isinstance(t, Mul) else (t,)
        num_factors, den_coeffs = [], [Fraction(1)]
        try:
            for f in factors:
                if isinstance(f, Pow) and isinstance(f.exp, Num) and f.exp.value < 0 and f.exp.value.denominator == 1:
                    base_coeffs = poly_coeffs(f.base, var)
                    for _ in range(-int(f.exp.value)):
                        den_coeffs = poly_mul(den_coeffs, base_coeffs)
                else:
                    num_factors.append(f)
            num_coeffs = poly_coeffs(mul(*num_factors) if num_factors else Num(1), var)
        except NotPolynomial:
            return e  # not a rational function we can handle -- leave as-is
        parts.append((num_coeffs, den_coeffs))

    if all(d == [Fraction(1)] for _, d in parts):
        return e  # no denominators at all -- nothing to cancel

    combined_den = [Fraction(1)]
    for _, d in parts:
        combined_den = poly_mul(combined_den, d)
    combined_num = [Fraction(0)]
    for n, d in parts:
        scale, _ = poly_div(combined_den, d)
        combined_num = poly_add(combined_num, poly_mul(n, scale))

    if any(c != 0 for c in combined_num):
        g = poly_gcd(combined_num, combined_den)
        if len(g) > 1:  # degree >= 1 common factor to cancel
            combined_num, _ = poly_div(combined_num, g)
            combined_den, _ = poly_div(combined_den, g)

    if len(combined_den) == 1:
        c = combined_den[0]
        return poly_from_coeffs([n / c for n in combined_num], var)

    num_expr = poly_from_coeffs(combined_num, var)
    den_expr = poly_from_coeffs(combined_den, var)
    return Mul((num_expr, pow_(den_expr, Num(-1))))
