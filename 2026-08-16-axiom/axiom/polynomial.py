"""Polynomial expansion, factoring, and GCD.

Axiom treats a "polynomial" as a single-variable view of an expression:
`poly_coeffs(expr, x)` walks a fully-expanded expression and returns
`{degree: coefficient}`, where each coefficient is itself an Expr that does
not contain `x` (so coefficients can be plain rationals, or — for the
multivariate case — expressions in other symbols; `factor()`/`poly_gcd()`
require rational-number coefficients, but `poly_coeffs`/`expand` do not).
"""

from fractions import Fraction

from .errors import AxiomError
from .expr import Add, Func, Mul, Num, Pow, Symbol, add, func, mul, num, power

# ---------------------------------------------------------------------------
# expand: fully distribute Mul over Add (and integer powers of Add)
# ---------------------------------------------------------------------------


def expand(e):
    if isinstance(e, (Num, Symbol)):
        return e
    if isinstance(e, Add):
        return add(*[expand(t) for t in e.terms])
    if isinstance(e, Mul):
        result = num(1)
        for f in e.factors:
            result = _distribute(result, expand(f))
        return result
    if isinstance(e, Pow):
        base = expand(e.base)
        exp = e.exp
        if (isinstance(exp, Num) and exp.value.denominator == 1
                and exp.value >= 0 and isinstance(base, Add)):
            n = int(exp.value)
            result = num(1)
            for _ in range(n):
                result = _distribute(result, base)
            return result
        return power(base, exp)
    if isinstance(e, Func):
        return func(e.name, expand(e.arg))
    raise TypeError(type(e))


def _distribute(a, b):
    a_terms = a.terms if isinstance(a, Add) else (a,)
    b_terms = b.terms if isinstance(b, Add) else (b,)
    return add(*[mul(x, y) for x in a_terms for y in b_terms])


# ---------------------------------------------------------------------------
# univariate coefficient extraction
# ---------------------------------------------------------------------------


def _factor_var_degree(f, var):
    if f == var:
        return 1
    if (isinstance(f, Pow) and f.base == var and isinstance(f.exp, Num)
            and f.exp.value.denominator == 1 and f.exp.value >= 0):
        return int(f.exp.value)
    return None


def _term_degree_coeff(term, var):
    d = _factor_var_degree(term, var)
    if d is not None:
        return d, num(1)
    if isinstance(term, Mul):
        deg = 0
        found = False
        coeff_factors = []
        for f in term.factors:
            fd = _factor_var_degree(f, var)
            if fd is not None:
                if found:
                    raise AxiomError(
                        f"not a polynomial in {var}: repeated variable factor")
                deg, found = fd, True
            else:
                if var in f.free_symbols():
                    raise AxiomError(
                        f"not a polynomial in {var}: '{f}' mixes {var} non-polynomially")
                coeff_factors.append(f)
        coeff = mul(*coeff_factors) if coeff_factors else num(1)
        return deg, coeff
    if var in term.free_symbols():
        raise AxiomError(f"not a polynomial in {var}: '{term}' mixes {var} non-polynomially")
    return 0, term


def poly_coeffs(expr, var):
    """Return {degree: coefficient-Expr} for `expr` viewed as a polynomial
    in `var`. Raises AxiomError if `expr` isn't a polynomial in `var`
    (negative/fractional exponents of `var`, or `var` inside a function)."""
    e = expand(expr)
    terms = e.terms if isinstance(e, Add) else (e,)
    coeffs = {}
    for t in terms:
        k, c = _term_degree_coeff(t, var)
        coeffs[k] = add(coeffs.get(k, num(0)), c)
    return coeffs


def poly_degree(expr, var):
    coeffs = poly_coeffs(expr, var)
    nonzero = [k for k, v in coeffs.items() if not (isinstance(v, Num) and v.value == 0)]
    return max(nonzero) if nonzero else 0


def _rational_coeff_list(coeffs, var, n):
    """coeffs dict -> ascending list of exactly-Fraction coefficients (index
    = degree), 0..n. Raises if any coefficient isn't a plain rational
    number (factor()/poly_gcd() only support rational-coefficient polys)."""
    out = []
    for k in range(n + 1):
        c = coeffs.get(k, num(0))
        if not isinstance(c, Num):
            raise AxiomError(
                f"factor()/gcd() need rational coefficients; the coefficient of "
                f"{var}^{k} is '{c}', not a number")
        out.append(c.value)
    return out


def coeffs_to_expr(coeffs_desc, var):
    """`coeffs_desc`: Fraction list, highest degree first. -> Expr."""
    n = len(coeffs_desc) - 1
    return add(*[mul(num(c), power(var, num(n - i))) for i, c in enumerate(coeffs_desc)])


# ---------------------------------------------------------------------------
# polynomial long division / GCD (Fraction coefficient lists, descending)
# ---------------------------------------------------------------------------


def _strip_leading_zeros(coeffs):
    i = 0
    while i < len(coeffs) - 1 and coeffs[i] == 0:
        i += 1
    return coeffs[i:]


def poly_divmod(a, b):
    """Divide polynomial `a` by `b` (both Fraction lists, descending order).
    Returns (quotient, remainder), both descending-order Fraction lists."""
    a = _strip_leading_zeros(list(a))
    b = _strip_leading_zeros(list(b))
    if all(c == 0 for c in b):
        raise AxiomError("polynomial division by zero")
    deg_b = len(b) - 1
    quotient = []
    remainder = list(a)
    while len(remainder) - 1 >= deg_b and not all(c == 0 for c in remainder):
        remainder = _strip_leading_zeros(remainder)
        if len(remainder) - 1 < deg_b:
            break
        factor = remainder[0] / b[0]
        deg_diff = (len(remainder) - 1) - deg_b
        quotient.append((deg_diff, factor))
        for i, bc in enumerate(b):
            remainder[i] -= factor * bc
        remainder = _strip_leading_zeros(remainder)
        if all(c == 0 for c in remainder):
            break
    if not quotient:
        q_list = [Fraction(0)]
    else:
        max_deg = quotient[0][0]
        q_list = [Fraction(0)] * (max_deg + 1)
        for d, c in quotient:
            q_list[max_deg - d] = c
    return q_list, remainder


def poly_gcd(p, q, var):
    """Monic GCD of two polynomial Exprs in `var`, via the Euclidean
    algorithm on rational-coefficient lists."""
    dp, dq = poly_degree(p, var), poly_degree(q, var)
    a = _rational_coeff_list(poly_coeffs(p, var), var, dp)[::-1]
    b = _rational_coeff_list(poly_coeffs(q, var), var, dq)[::-1]
    a, b = _strip_leading_zeros(a), _strip_leading_zeros(b)
    while not all(c == 0 for c in b):
        _, r = poly_divmod(a, b)
        a, b = b, r
    a = _strip_leading_zeros(a)
    if a[0] != 0:
        a = [c / a[0] for c in a]
    return coeffs_to_expr(a, var)


# ---------------------------------------------------------------------------
# factor(): pull out rational roots via the rational root theorem, then
# fall back to the quadratic formula (with exact/radical sqrt) for any
# degree-2 remainder. Higher-degree factors with no rational root are left
# irreducible (documented limitation — full factoring over Q needs
# Berlekamp/Zassenhaus-style algorithms, out of scope for this build).
# ---------------------------------------------------------------------------


def _divisors(n):
    n = abs(n)
    if n == 0:
        return [1]
    out = set()
    i = 1
    while i * i <= n:
        if n % i == 0:
            out.add(i)
            out.add(n // i)
        i += 1
    return sorted(out)


def _rational_root_candidates(coeffs_desc):
    """coeffs_desc: Fraction list, descending, monic-or-not. Returns
    candidate rational roots via p/q where p | constant term (cleared to an
    integer) and q | leading term (cleared to an integer)."""
    denoms = [c.denominator for c in coeffs_desc]
    lcm = 1
    for d in denoms:
        lcm = lcm * d // _gcd(lcm, d)
    int_coeffs = [int(c * lcm) for c in coeffs_desc]
    const, lead = int_coeffs[-1], int_coeffs[0]
    candidates = set()
    if const == 0:
        candidates.add(Fraction(0))
        int_coeffs_nz = int_coeffs[:-1]
        while int_coeffs_nz and int_coeffs_nz[-1] == 0:
            const = 0
            int_coeffs_nz = int_coeffs_nz[:-1]
        const = int_coeffs_nz[-1] if int_coeffs_nz else 0
    for p in _divisors(const) if const != 0 else [0]:
        for q in _divisors(lead):
            if p == 0:
                continue
            candidates.add(Fraction(p, q))
            candidates.add(Fraction(-p, q))
    return candidates


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def _eval_poly(coeffs_desc, x):
    result = Fraction(0)
    for c in coeffs_desc:
        result = result * x + c
    return result


def _synthetic_divide(coeffs_desc, root):
    """Divide monic-or-not poly (descending Fraction list) by (x - root),
    assuming `root` is an exact root. Returns the quotient (descending)."""
    quotient = [coeffs_desc[0]]
    for c in coeffs_desc[1:-1]:
        quotient.append(quotient[-1] * root + c)
    return quotient


def peel_rational_roots(coeffs_desc):
    """`coeffs_desc`: Fraction list, descending, any leading coefficient.
    Repeatedly finds and divides out rational roots via the rational root
    theorem + synthetic division. Returns (roots, remaining_coeffs_desc)
    where `roots` is a flat list (with multiplicity) of exact Fraction
    roots and `remaining_coeffs_desc` is what's left (same leading
    coefficient convention as the input, degree possibly 0)."""
    coeffs_desc = _strip_leading_zeros(list(coeffs_desc))
    lc = coeffs_desc[0]
    remaining = [c / lc for c in coeffs_desc]  # work monic, rescale not needed for roots
    roots = []
    while len(remaining) - 1 >= 1:
        remaining = _strip_leading_zeros(remaining)
        if len(remaining) - 1 < 1:
            break
        found = None
        for cand in sorted(_rational_root_candidates(remaining), key=lambda r: (abs(r), r)):
            if _eval_poly(remaining, cand) == 0:
                found = cand
                break
        if found is None:
            break
        roots.append(found)
        remaining = _synthetic_divide(remaining, found)
    return roots, _strip_leading_zeros(remaining)


def factor(expr, var=None):
    """Factor `expr` (a single-variable, rational-coefficient polynomial)
    into `lc * (x - r1)^m1 * (x - r2)^m2 * ... * [irreducible remainder]`.
    Every root — rational or an exact/radical quadratic-formula root — is
    verified by re-expansion in the test suite, not just "found"."""
    e = expand(expr)
    fs = e.free_symbols()
    if var is None:
        if len(fs) == 0:
            return e
        if len(fs) > 1:
            raise AxiomError(
                f"factor() needs a single variable, expr has {sorted(s.name for s in fs)} "
                f"— pass var= explicitly")
        var = next(iter(fs))

    n = poly_degree(e, var)
    if n == 0:
        return e
    coeffs_asc = _rational_coeff_list(poly_coeffs(e, var), var, n)
    coeffs_desc = coeffs_asc[::-1]
    coeffs_desc = _strip_leading_zeros(coeffs_desc)
    lc = coeffs_desc[0]
    roots, remaining = peel_rational_roots(coeffs_desc)
    deg_left = len(remaining) - 1

    factors_expr = []
    root_mult = {}
    for r in roots:
        root_mult[r] = root_mult.get(r, 0) + 1
    for r, m in root_mult.items():
        term = add(var, num(-r))
        factors_expr.append(power(term, num(m)))

    if deg_left == 1:
        a, b = remaining
        r = -b / a
        factors_expr.append(add(var, num(-r)))
    elif deg_left == 2:
        a, b, c = remaining  # monic: a == 1
        disc = b * b - 4 * a * c
        if disc >= 0:
            sqrt_disc = power(num(disc), num(Fraction(1, 2)))
            r1 = mul(num(Fraction(1, 2)), add(mul(num(-1), num(b)), sqrt_disc))
            r2 = mul(num(Fraction(1, 2)), add(mul(num(-1), num(b)), mul(num(-1), sqrt_disc)))
            factors_expr.append(add(var, mul(num(-1), r1)))
            factors_expr.append(add(var, mul(num(-1), r2)))
        else:
            factors_expr.append(coeffs_to_expr(remaining, var))
    elif deg_left >= 3:
        factors_expr.append(coeffs_to_expr(remaining, var))

    if lc != 1 or not factors_expr:
        factors_expr.insert(0, num(lc))
    return mul(*factors_expr)
