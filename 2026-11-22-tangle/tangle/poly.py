"""Laurent polynomials over Z, stored as {exponent: coefficient} (no zero terms)."""
from fractions import Fraction


def clean(p):
    return {e: c for e, c in p.items() if c}


def add(p, q):
    r = dict(p)
    for e, c in q.items():
        r[e] = r.get(e, 0) + c
    return clean(r)


def scale(p, k):
    return clean({e: c * k for e, c in p.items()})


def shift(p, k):
    return {e + k: c for e, c in p.items()}


def mul(p, q):
    r = {}
    for e1, c1 in p.items():
        for e2, c2 in q.items():
            r[e1 + e2] = r.get(e1 + e2, 0) + c1 * c2
    return clean(r)


def divide_exact(p, q):
    """Exact Laurent division p/q; raises ValueError if q does not divide p."""
    if not q:
        raise ZeroDivisionError("division by zero polynomial")
    rem = dict(p)
    out = {}
    qtop, qlead = max(q), q[max(q)]
    lowest = (min(p) - min(q)) if p else 0   # quotient has no term below this
    while rem:
        rtop = max(rem)
        k = rtop - qtop
        if k < lowest or rem[rtop] % qlead:
            raise ValueError("inexact division")
        c = rem[rtop] // qlead
        out[k] = c
        for e, qc in q.items():
            rem[e + k] = rem.get(e + k, 0) - qc * c
        rem = clean(rem)
    return out


def evaluate(p, x):
    return sum(c * Fraction(x) ** e for e, c in p.items())


def interpolate(xs, ys):
    """Lagrange interpolation over Q; returns {exp: Fraction} for exps 0..len-1."""
    n = len(xs)
    coeffs = [Fraction(0)] * n
    for i in range(n):
        # basis polynomial
        basis = [Fraction(1)]
        denom = Fraction(1)
        for j in range(n):
            if j == i:
                continue
            new = [Fraction(0)] * (len(basis) + 1)
            for k, b in enumerate(basis):
                new[k + 1] += b
                new[k] -= b * xs[j]
            basis = new
            denom *= xs[i] - xs[j]
        for k, b in enumerate(basis):
            coeffs[k] += ys[i] * b / denom
    return coeffs


def fmt(p, var="t", unit=1):
    """Pretty-print. Exponent e is shown as var^(e/unit)."""
    if not p:
        return "0"
    parts = []
    for e in sorted(p):
        c = p[e]
        ex = Fraction(e, unit)
        if ex == 0:
            body = str(abs(c))
        else:
            mag = "" if abs(c) == 1 else str(abs(c))
            if ex == 1:
                s = var
            elif ex.denominator == 1:
                s = f"{var}^{ex.numerator}"
            else:
                s = f"{var}^({ex.numerator}/{ex.denominator})"
            body = mag + s
        parts.append(("-" if c < 0 else "+", body))
    out = ("-" if parts[0][0] == "-" else "") + parts[0][1]
    for sign, body in parts[1:]:
        out += f" {sign} {body}"
    return out
