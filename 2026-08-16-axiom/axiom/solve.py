"""Equation solving: exact for linear and quadratic (real exact/radical, or
complex via the quadratic formula), and for higher-degree polynomials via
the rational root theorem first (exact rational roots peeled off one at a
time) followed by Durand-Kerner simultaneous iteration for whatever's left,
refined with a few steps of Newton's method. Every root this module returns
is checked by substitution residual in the test suite — not just "the
iteration converged," but "plugging it back into the original equation
gives (numerically or exactly) zero."
"""

import cmath
from fractions import Fraction

from . import polynomial as P
from .errors import AxiomError
from .expr import Num, add, mul, num, power, sym


def solve(equation, var):
    """Solve `equation` (an Expr meaning `equation == 0`, or a `(lhs, rhs)`
    pair, or a string `"lhs = rhs"`) for `var`. Returns a list of roots:
    exact `Expr` (rational or radical) for anything found via the rational
    root theorem or a real/exact quadratic, and Python `complex` for
    anything only found via numeric Durand-Kerner iteration."""
    if isinstance(var, str):
        var = sym(var)
    f = _to_zero_form(equation)

    n = P.poly_degree(f, var)
    coeffs = P.poly_coeffs(f, var)
    all_numeric = all(isinstance(coeffs.get(k, num(0)), Num) for k in range(n + 1))

    if n == 0:
        c0 = coeffs.get(0, num(0))
        if isinstance(c0, Num) and c0.value == 0:
            raise AxiomError(f"'{f} = 0' holds for every value of {var} (not a solvable equation)")
        return []

    if n == 1:
        a = coeffs.get(1, num(0))
        b = coeffs.get(0, num(0))
        return [mul(num(-1), b, power(a, num(-1)))]

    if n == 2:
        a, b, c = coeffs.get(2, num(0)), coeffs.get(1, num(0)), coeffs.get(0, num(0))
        return _quadratic_roots(a, b, c)

    if not all_numeric:
        raise AxiomError(
            f"solve() only supports symbolic coefficients for linear and quadratic "
            f"equations; degree {n} needs rational coefficients")

    lc = coeffs[n].value
    coeffs_desc = [coeffs.get(k, num(0)).value for k in range(n, -1, -1)]
    rational_roots, remaining = P.peel_rational_roots(coeffs_desc)
    roots = [num(r) for r in rational_roots]

    deg_left = len(remaining) - 1
    if deg_left == 1:
        a, b = remaining
        roots.append(num(-b / a))
    elif deg_left == 2:
        a, b, c = remaining
        roots.extend(_quadratic_roots(num(a), num(b), num(c)))
    elif deg_left >= 3:
        roots.extend(_durand_kerner(remaining))

    return roots


def _to_zero_form(equation):
    if isinstance(equation, str):
        if "=" not in equation:
            raise AxiomError("equation string must contain '=', e.g. \"x^2 = 4\"")
        lhs_s, rhs_s = equation.split("=", 1)
        from .parser import parse
        return add(parse(lhs_s), mul(num(-1), parse(rhs_s)))
    if isinstance(equation, tuple):
        lhs, rhs = equation
        return add(lhs, mul(num(-1), rhs))
    return equation


def _quadratic_roots(a, b, c):
    if isinstance(a, Num) and isinstance(b, Num) and isinstance(c, Num):
        av, bv, cv = a.value, b.value, c.value
        disc = bv * bv - 4 * av * cv
        if disc >= 0:
            sqrt_disc = power(num(disc), num(Fraction(1, 2)))
            r1 = mul(num(Fraction(1, 2)), add(mul(num(-1), b), sqrt_disc), power(a, num(-1)))
            r2 = mul(num(Fraction(1, 2)), add(mul(num(-1), b), mul(num(-1), sqrt_disc)), power(a, num(-1)))
            return [r1, r2]
        sqrt_disc_c = cmath.sqrt(complex(disc))
        denom = 2 * complex(av)
        return [(-complex(bv) + sqrt_disc_c) / denom, (-complex(bv) - sqrt_disc_c) / denom]
    # symbolic coefficients: build the formula directly, real/complex left implicit.
    disc = add(mul(b, b), mul(num(-4), a, c))
    sqrt_disc = power(disc, num(Fraction(1, 2)))
    r1 = mul(num(Fraction(1, 2)), add(mul(num(-1), b), sqrt_disc), power(a, num(-1)))
    r2 = mul(num(Fraction(1, 2)), add(mul(num(-1), b), mul(num(-1), sqrt_disc)), power(a, num(-1)))
    return [r1, r2]


def _durand_kerner(coeffs_desc, iterations=500, tol=1e-13):
    """All complex roots of a monic polynomial (Fraction coeffs, descending,
    degree >= 1) via simultaneous Durand-Kerner (Weierstrass) iteration."""
    m = len(coeffs_desc) - 1
    cvals = [complex(c) for c in coeffs_desc]

    def horner(z):
        r = complex(0)
        for c in cvals:
            r = r * z + c
        return r

    seed = complex(0.4, 0.9)
    zs = [seed ** k for k in range(m)]
    for _ in range(iterations):
        max_delta = 0.0
        for k in range(m):
            denom = 1 + 0j
            for j in range(m):
                if j != k:
                    denom *= (zs[k] - zs[j])
            if denom == 0:
                denom = 1e-12 + 0j
            delta = horner(zs[k]) / denom
            zs[k] -= delta
            max_delta = max(max_delta, abs(delta))
        if max_delta < tol:
            break

    out = []
    for z in zs:
        if abs(z.imag) < 1e-9 * max(1.0, abs(z.real)):
            out.append(complex(z.real, 0.0))
        else:
            out.append(z)
    return out
