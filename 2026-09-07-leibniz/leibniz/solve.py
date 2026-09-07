"""Exact equation solving: linear, quadratic, general polynomial (via
rational-root extraction down to a quadratic remainder, then a numeric
fallback for any irreducible-over-the-rationals higher-degree remainder),
and linear systems via exact Gaussian-Jordan elimination."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .expr import Expr, Num, Symbol, func_
from .polynomial import NotPolynomial, _rational_root_candidates, _strip, poly_coeffs, poly_div, poly_eval
from .simplify import simplify


class SolveError(Exception):
    pass


@dataclass
class SolveResult:
    roots: list = field(default_factory=list)          # exact Expr solutions
    numeric_roots: list = field(default_factory=list)  # approximate complex roots, only when exact extraction ran out
    infinite: bool = False                              # equation is 0 = 0

    @property
    def no_solution(self) -> bool:
        return not self.roots and not self.numeric_roots and not self.infinite


def solve_quadratic(a: Expr, b: Expr, c: Expr) -> list[Expr]:
    """Exact roots of a*x**2 + b*x + c, a != 0. Always returns two entries
    (equal, for a double root). The discriminant's square root is kept
    exactly symbolic (Func('sqrt', ...)) when irrational, and becomes an
    exact multiple of i (Leibniz's imaginary unit) when negative -- never a
    float."""
    disc = b * b - Num(4) * a * c
    sqrt_disc = func_("sqrt", disc)
    two_a = Num(2) * a
    r1 = simplify((Num(-1) * b + sqrt_disc) / two_a)
    r2 = simplify((Num(-1) * b - sqrt_disc) / two_a)
    return [r1, r2]


def solve(lhs: Expr, rhs: Expr, var: str) -> SolveResult:
    """Solve lhs == rhs for `var`."""
    diff = simplify(lhs - rhs)
    try:
        coeffs = poly_coeffs(diff, var)
    except NotPolynomial as ex:
        raise SolveError(str(ex)) from ex

    if all(c == 0 for c in coeffs):
        return SolveResult(infinite=True)

    degree = len(coeffs) - 1
    if degree == 0:
        return SolveResult()  # coeffs[0] != 0 here -> no solution
    if degree == 1:
        a, b = coeffs[1], coeffs[0]
        return SolveResult(roots=[Num(-b / a)])
    if degree == 2:
        a, b, c = coeffs[2], coeffs[1], coeffs[0]
        return SolveResult(roots=solve_quadratic(Num(a), Num(b), Num(c)))

    # degree >= 3: peel off rational roots one at a time
    exact_roots: list[Expr] = []
    work = coeffs[:]
    while len(work) - 1 >= 3:
        found = None
        for r in _rational_root_candidates(work):
            if poly_eval(work, r) == 0:
                found = r
                break
        if found is None:
            break
        exact_roots.append(Num(found))
        work, _ = poly_div(work, [-found, Fraction(1)])
        work = _strip(work)

    remaining_degree = len(work) - 1
    if remaining_degree == 2:
        a, b, c = work[2], work[1], work[0]
        exact_roots.extend(solve_quadratic(Num(a), Num(b), Num(c)))
        return SolveResult(roots=exact_roots)
    if remaining_degree == 1:
        a, b = work[1], work[0]
        exact_roots.append(Num(-b / a))
        return SolveResult(roots=exact_roots)
    if remaining_degree == 0:
        return SolveResult(roots=exact_roots)

    # remaining_degree >= 3, no more rational roots: numeric fallback
    numeric = _numeric_roots(work)
    return SolveResult(roots=exact_roots, numeric_roots=numeric)


def _numeric_roots(coeffs: list[Fraction], iterations: int = 300) -> list[complex]:
    """Durand-Kerner simultaneous iteration for all (possibly complex) roots
    of a polynomial with real coefficients. Used only for the degree>=3
    remainder once rational-root extraction has exhausted exact options."""
    n = len(coeffs) - 1
    lead = float(coeffs[-1])
    c = [float(x) / lead for x in coeffs]  # monic, low-to-high

    def p(z):
        result = 0j
        for coeff in reversed(c):
            result = result * z + coeff
        return result

    roots = [complex(0.4, 0.9) ** k for k in range(1, n + 1)]
    for _ in range(iterations):
        new_roots = []
        for i in range(n):
            zi = roots[i]
            denom = 1 + 0j
            for j in range(n):
                if j != i:
                    denom *= zi - roots[j]
            if denom == 0:
                denom = 1e-12
            new_roots.append(zi - p(zi) / denom)
        roots = new_roots

    cleaned = []
    for r in roots:
        real = r.real if abs(r.real) > 1e-9 else 0.0
        imag = r.imag if abs(r.imag) > 1e-9 else 0.0
        cleaned.append(complex(real, imag))
    return cleaned


# ---------------------------------------------------------------------------
# linear systems
# ---------------------------------------------------------------------------


class LinearSystemError(Exception):
    pass


@dataclass
class LinearSystemResult:
    solution: dict | None = None   # var name -> Expr, if unique
    infinite: bool = False
    inconsistent: bool = False


def _linear_term(t: Expr, names: set):
    from .expr import Mul

    if isinstance(t, Num):
        return t.value, None
    if isinstance(t, Symbol):
        if t.name in names:
            return Fraction(1), t.name
        raise LinearSystemError(f"unexpected free variable {t.name!r}")
    if isinstance(t, Mul):
        coeff, varname = Fraction(1), None
        for f in t.args:
            if isinstance(f, Num):
                coeff *= f.value
            elif isinstance(f, Symbol) and f.name in names:
                if varname is not None:
                    raise LinearSystemError(f"nonlinear term (product of variables): {t}")
                varname = f.name
            else:
                raise LinearSystemError(f"nonlinear term: {t}")
        return coeff, varname
    raise LinearSystemError(f"nonlinear term: {t}")


def linear_coeffs(expr: Expr, names: list):
    from .expr import Add

    expr = simplify(expr)
    names_set = set(names)
    terms = expr.args if isinstance(expr, Add) else (expr,)
    coeffs = {v: Fraction(0) for v in names}
    const = Fraction(0)
    for t in terms:
        c, varname = _linear_term(t, names_set)
        if varname is None:
            const += c
        else:
            coeffs[varname] += c
    return coeffs, const


def solve_linear_system(equations: list, names: list) -> LinearSystemResult:
    """equations: list of (lhs, rhs) Expr pairs, each linear in `names`."""
    n = len(names)
    rows = []
    for lhs, rhs in equations:
        coeffs, const = linear_coeffs(lhs - rhs, names)
        rows.append([coeffs[v] for v in names] + [-const])

    m = len(rows)
    row_idx = 0
    pivot_cols = []
    for col in range(n):
        pivot = next((r for r in range(row_idx, m) if rows[r][col] != 0), None)
        if pivot is None:
            continue
        rows[row_idx], rows[pivot] = rows[pivot], rows[row_idx]
        pv = rows[row_idx][col]
        rows[row_idx] = [v / pv for v in rows[row_idx]]
        for r in range(m):
            if r != row_idx and rows[r][col] != 0:
                factor_ = rows[r][col]
                rows[r] = [a - factor_ * b for a, b in zip(rows[r], rows[row_idx])]
        pivot_cols.append(col)
        row_idx += 1

    for r in range(row_idx, m):
        if all(c == 0 for c in rows[r][:n]) and rows[r][n] != 0:
            return LinearSystemResult(inconsistent=True)

    if row_idx < n:
        return LinearSystemResult(infinite=True)

    solution = {names[i]: Num(rows[i][n]) for i in range(n)}
    return LinearSystemResult(solution=solution)
