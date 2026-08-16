"""Explicit simplification beyond the automatic canonicalization every
smart constructor already performs. Because `add()`/`mul()`/`power()` fold
constants, collect like terms, and apply exponent laws *at construction
time*, any Axiom expression is already close to canonical the moment it's
built. `simplify()` re-canonicalizes an arbitrary tree (useful if it was
built by hand rather than through the smart constructors) and then applies
a small number of additional, genuinely non-trivial rewrite passes:

  1. Pythagorean identity: sin(u)**2 + cos(u)**2 -> 1 (and scalar multiples
     of the same pattern), wherever it appears inside a sum.
  2. Rational function reduction: cancel a common polynomial factor between
     a numerator and a Pow(denominator, -1) factor of the same Mul, via
     polynomial GCD — e.g. (x**2-1)/(x-1) -> x+1.

Each pass is optional and independently toggle-able; `simplify(expr, trace=[])`
appends a human-readable line every time a pass actually changes something,
which is what the HTML visualizer's step-by-step view renders.
"""

from .expr import Add, Func, Mul, Num, Pow, Symbol, add, func, mul, num, power


def _canonicalize(e):
    if isinstance(e, (Num, Symbol)):
        return e
    if isinstance(e, Add):
        return add(*[_canonicalize(t) for t in e.terms])
    if isinstance(e, Mul):
        return mul(*[_canonicalize(f) for f in e.factors])
    if isinstance(e, Pow):
        return power(_canonicalize(e.base), _canonicalize(e.exp))
    if isinstance(e, Func):
        return func(e.name, _canonicalize(e.arg))
    raise TypeError(type(e))


def _term_signature(term):
    """(coefficient, base-without-coefficient) for an Add term."""
    if isinstance(term, Mul) and term.factors and isinstance(term.factors[0], Num):
        rest = term.factors[1:]
        base = rest[0] if len(rest) == 1 else Mul(rest)
        return term.factors[0].value, base
    return 1, term


def _rebuild_if_changed(e):
    """Recursively apply the sin²+cos²=1 reduction bottom-up."""
    if isinstance(e, (Num, Symbol)):
        return e, False
    if isinstance(e, Add):
        results = [_pythagorean_pass_inner(t) for t in e.terms]
        new_terms = [r for r, _ in results]
        changed = any(c for _, c in results)
        rebuilt = add(*new_terms)
        rebuilt2, changed2 = _pythagorean_reduce_once(rebuilt)
        return rebuilt2, changed or changed2
    if isinstance(e, Mul):
        results = [_pythagorean_pass_inner(f) for f in e.factors]
        new_factors = [r for r, _ in results]
        changed = any(c for _, c in results)
        return mul(*new_factors), changed
    if isinstance(e, Pow):
        b, cb = _pythagorean_pass_inner(e.base)
        x, cx = _pythagorean_pass_inner(e.exp)
        return power(b, x), cb or cx
    if isinstance(e, Func):
        a, c = _pythagorean_pass_inner(e.arg)
        return func(e.name, a), c
    raise TypeError(type(e))


def _pythagorean_pass_inner(e):
    return _rebuild_if_changed(e)


def _pythagorean_reduce_once(e):
    if not isinstance(e, Add):
        return e, False
    terms = list(e.terms)
    sin_sq, cos_sq = {}, {}
    for i, t in enumerate(terms):
        coeff, base = _term_signature(t)
        if isinstance(base, Pow) and isinstance(base.exp, Num) and base.exp.value == 2:
            inner = base.base
            if isinstance(inner, Func) and inner.name == "sin":
                sin_sq.setdefault(inner.arg, []).append((i, coeff))
            elif isinstance(inner, Func) and inner.name == "cos":
                cos_sq.setdefault(inner.arg, []).append((i, coeff))
    drop = set()
    extra_const = 0
    changed = False
    for arg_, sins in sin_sq.items():
        if arg_ in cos_sq:
            n = min(len(sins), len(cos_sq[arg_]))
            for k in range(n):
                si, sc = sins[k]
                ci, cc = cos_sq[arg_][k]
                if sc == cc and si not in drop and ci not in drop:
                    drop.add(si)
                    drop.add(ci)
                    extra_const += sc
                    changed = True
    if not changed:
        return e, False
    kept = [t for i, t in enumerate(terms) if i not in drop]
    kept.append(num(extra_const))
    return add(*kept), True


def _rational_reduce(e):
    """Cancel a common polynomial factor between a Mul's plain factors and
    its Pow(base, negative)-denominator factors, via single-variable
    polynomial GCD, when exactly one free symbol is involved."""
    from . import polynomial as P
    from .errors import AxiomError

    if not isinstance(e, Mul):
        return _map_children(e, _rational_reduce)
    e = _map_children(e, _rational_reduce)
    if not isinstance(e, Mul):
        return e
    num_factors, den_factors = [], []
    for f in e.factors:
        if isinstance(f, Pow) and isinstance(f.exp, Num) and f.exp.value < 0:
            den_factors.append(power(f.base, num(-f.exp.value)))
        else:
            num_factors.append(f)
    if not den_factors or not num_factors:
        return e
    numerator = mul(*num_factors)
    denominator = mul(*den_factors)
    fs = numerator.free_symbols() | denominator.free_symbols()
    if len(fs) != 1:
        return e
    var = next(iter(fs))
    try:
        g = P.poly_gcd(numerator, denominator, var)
    except AxiomError:
        return e
    if isinstance(g, Num) and g.value == 1:
        return e
    try:
        new_num_q, new_num_r = P.poly_divmod(
            [c.value for c in _desc_coeffs(numerator, var)],
            [c.value for c in _desc_coeffs(g, var)])
        new_den_q, new_den_r = P.poly_divmod(
            [c.value for c in _desc_coeffs(denominator, var)],
            [c.value for c in _desc_coeffs(g, var)])
    except AxiomError:
        return e
    if any(r != 0 for r in new_num_r) or any(r != 0 for r in new_den_r):
        return e
    new_num_expr = P.coeffs_to_expr(new_num_q, var)
    new_den_expr = P.coeffs_to_expr(new_den_q, var)
    return mul(new_num_expr, power(new_den_expr, num(-1)))


def _desc_coeffs(expr, var):
    from . import polynomial as P
    d = P.poly_degree(expr, var)
    coeffs = P.poly_coeffs(expr, var)
    return [coeffs.get(k, num(0)) for k in range(d, -1, -1)]


def _map_children(e, f):
    if isinstance(e, (Num, Symbol)):
        return e
    if isinstance(e, Add):
        return add(*[f(t) for t in e.terms])
    if isinstance(e, Mul):
        return mul(*[f(x) for x in e.factors])
    if isinstance(e, Pow):
        return power(f(e.base), f(e.exp))
    if isinstance(e, Func):
        return func(e.name, f(e.arg))
    raise TypeError(type(e))


def simplify(expr, trace=None):
    """Simplify `expr` to canonical form plus the extra rewrite passes
    described above. If `trace` is a list, human-readable step descriptions
    are appended to it whenever a pass actually changes the expression."""
    e = _canonicalize(expr)
    if trace is not None:
        trace.append(f"canonicalize: {e}")

    e2, changed = _rebuild_if_changed(e)
    if changed:
        e = e2
        if trace is not None:
            trace.append(f"apply sin²+cos² = 1: {e}")

    e3 = _rational_reduce(e)
    if e3 != e:
        e = e3
        if trace is not None:
            trace.append(f"cancel common polynomial factor: {e}")

    return e
