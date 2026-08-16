"""The Axiom expression AST and its canonicalizing smart constructors.

Every node type (Num, Symbol, Add, Mul, Pow, Func) is an immutable, hashable,
structurally-comparable frozen dataclass — this is what makes an Axiom
expression usable as a dict key (needed for like-term collection) and lets
`a == b` mean "these two trees have identical structure," not "these two
objects are the same instance."

The module-level functions `add()`, `mul()`, `power()`, `func()` are smart
constructors: they don't just build a node, they canonicalize (flatten
nested sums/products, fold exact rational arithmetic via `fractions.Fraction`,
collect like terms, apply exponent laws, extract exact/partial radicals).
Every other module in Axiom (the parser, differentiation, integration,
polynomial expansion, equation solving) builds expressions exclusively
through these functions, so the *only* place auto-simplification logic lives
is here — every result that comes out of the kernel is already in a
canonical, comparable form.
"""

import cmath
import math
from dataclasses import dataclass
from fractions import Fraction

from .errors import AxiomError, DomainError

# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------


class Expr:
    """Common base for every expression node. Operator overloads route
    through the canonicalizing smart constructors below, so ordinary Python
    arithmetic on Axiom expressions (`2*x + 1`) produces canonical trees."""

    def __add__(self, other):
        return add(self, _coerce(other))

    def __radd__(self, other):
        return add(_coerce(other), self)

    def __sub__(self, other):
        return add(self, mul(num(-1), _coerce(other)))

    def __rsub__(self, other):
        return add(_coerce(other), mul(num(-1), self))

    def __mul__(self, other):
        return mul(self, _coerce(other))

    def __rmul__(self, other):
        return mul(_coerce(other), self)

    def __truediv__(self, other):
        return mul(self, power(_coerce(other), num(-1)))

    def __rtruediv__(self, other):
        return mul(_coerce(other), power(self, num(-1)))

    def __pow__(self, other):
        return power(self, _coerce(other))

    def __rpow__(self, other):
        return power(_coerce(other), self)

    def __neg__(self):
        return mul(num(-1), self)

    def __pos__(self):
        return self

    # -- structural helpers --------------------------------------------

    @property
    def args(self):
        return ()

    def free_symbols(self):
        out = set()
        _collect_symbols(self, out)
        return out

    def is_number(self):
        return isinstance(self, Num)

    def subs(self, mapping):
        """Structural substitution. `mapping`: dict of Symbol|str -> Expr|number."""
        m = {(k if isinstance(k, str) else k.name): _coerce(v) for k, v in mapping.items()}
        return _subs(self, m)

    def evalf(self, bindings=None):
        """Evaluate to a Python complex number. Raises DomainError if a free
        symbol is unbound or the operation is undefined at this point."""
        b = {}
        if bindings:
            for k, v in bindings.items():
                name = k if isinstance(k, str) else k.name
                b[name] = complex(v)
        return _evalf(self, b)

    def __str__(self):
        return to_str(self)

    def __repr__(self):
        return to_str(self)

    def latex(self):
        from .latex import to_latex
        return to_latex(self)


@dataclass(frozen=True, order=False, repr=False)
class Num(Expr):
    value: Fraction

    def __post_init__(self):
        if not isinstance(self.value, Fraction):
            object.__setattr__(self, "value", Fraction(self.value))


@dataclass(frozen=True, order=False, repr=False)
class Symbol(Expr):
    name: str


@dataclass(frozen=True, order=False, repr=False)
class Add(Expr):
    terms: tuple

    @property
    def args(self):
        return self.terms


@dataclass(frozen=True, order=False, repr=False)
class Mul(Expr):
    factors: tuple

    @property
    def args(self):
        return self.factors


@dataclass(frozen=True, order=False, repr=False)
class Pow(Expr):
    base: Expr
    exp: Expr

    @property
    def args(self):
        return (self.base, self.exp)


@dataclass(frozen=True, order=False, repr=False)
class Func(Expr):
    name: str
    arg: Expr

    @property
    def args(self):
        return (self.arg,)


# ---------------------------------------------------------------------------
# convenience constructors
# ---------------------------------------------------------------------------


def sym(name):
    return Symbol(name)


def symbols(names):
    """`symbols('x y z')` -> tuple of Symbol."""
    return tuple(Symbol(n) for n in names.replace(",", " ").split())


def num(value):
    if isinstance(value, Num):
        return value
    if isinstance(value, Fraction):
        return Num(value)
    if isinstance(value, int):
        return Num(Fraction(value))
    if isinstance(value, float):
        return Num(Fraction(value).limit_denominator(10 ** 12))
    raise TypeError(f"cannot build Num from {value!r}")


def _coerce(x):
    if isinstance(x, Expr):
        return x
    return num(x)


ZERO = Num(Fraction(0))
ONE = Num(Fraction(1))
NEG_ONE = Num(Fraction(-1))

FUNC_NAMES = ("sin", "cos", "tan", "exp", "log", "sqrt", "abs",
              "asin", "acos", "atan", "sinh", "cosh", "tanh")


def func(name, argument):
    if name not in FUNC_NAMES:
        raise AxiomError(f"unknown function '{name}'")
    argument = _coerce(argument)
    # A handful of exact evaluations at "nice" points keep the tree small
    # and let identities like sin(0)=0 fall out for free.
    if isinstance(argument, Num):
        exact = _exact_func_value(name, argument.value)
        if exact is not None:
            return num(exact)
    if name == "sqrt":
        return power(argument, Num(Fraction(1, 2)))
    if name == "log" and isinstance(argument, Func) and argument.name == "exp":
        return argument.arg
    if name == "exp" and isinstance(argument, Func) and argument.name == "log":
        return argument.arg
    return Func(name, argument)


_EXACT_FUNC_TABLE = {
    ("sin", Fraction(0)): Fraction(0),
    ("cos", Fraction(0)): Fraction(1),
    ("tan", Fraction(0)): Fraction(0),
    ("exp", Fraction(0)): Fraction(1),
    ("sinh", Fraction(0)): Fraction(0),
    ("cosh", Fraction(0)): Fraction(1),
    ("tanh", Fraction(0)): Fraction(0),
    ("asin", Fraction(0)): Fraction(0),
    ("atan", Fraction(0)): Fraction(0),
    ("abs", Fraction(0)): Fraction(0),
}


def _exact_func_value(name, value):
    if name == "log" and value == 1:
        return Fraction(0)
    if name == "abs":
        return abs(value)
    return _EXACT_FUNC_TABLE.get((name, value))


# ---------------------------------------------------------------------------
# canonical ordering (used both for sorting terms/factors and for grouping
# structurally-equal pieces together)
# ---------------------------------------------------------------------------

_KIND_RANK = {Symbol: 0, Pow: 1, Func: 2, Mul: 3, Add: 4, Num: 5}


def sort_key(e):
    return (_KIND_RANK[type(e)], to_str(e))


def _poly_degree_score(e):
    """A rough total-degree heuristic used only to order Add's terms in the
    familiar "highest degree first" way (x^3 + 3x^2 + 3x + 1, not some
    degree-blind string order) — not a real multivariate degree function."""
    if isinstance(e, Num):
        return Fraction(0)
    if isinstance(e, Symbol):
        return Fraction(1)
    if isinstance(e, Pow) and isinstance(e.exp, Num):
        return e.exp.value
    if isinstance(e, Mul):
        return sum((_poly_degree_score(f) for f in e.factors), Fraction(0))
    return Fraction(1)  # Func call or a non-numeric-exponent Pow


def _add_term_key(e):
    return (-_poly_degree_score(e), sort_key(e))


# ---------------------------------------------------------------------------
# smart Add
# ---------------------------------------------------------------------------


def add(*args):
    flat = []
    for a in args:
        a = _coerce(a)
        if isinstance(a, Add):
            flat.extend(a.terms)
        else:
            flat.append(a)

    const = Fraction(0)
    # term -> accumulated coefficient, term stored in `rest[key]`
    coeffs = {}
    order = []
    for t in flat:
        if isinstance(t, Num):
            const += t.value
            continue
        coeff, rest = _strip_coeff(t)
        key = rest
        if key not in coeffs:
            coeffs[key] = Fraction(0)
            order.append(key)
        coeffs[key] += coeff

    terms = []
    for key in order:
        c = coeffs[key]
        if c == 0:
            continue
        terms.append(_apply_coeff(c, key))
    terms.sort(key=_add_term_key)

    if const != 0 or not terms:
        terms.append(num(const))

    if len(terms) == 1:
        return terms[0]
    return Add(tuple(terms))


def _strip_coeff(term):
    """Split a term into (rational coefficient, remaining-Expr-as-dict-key)."""
    if isinstance(term, Mul):
        factors = term.factors
        if factors and isinstance(factors[0], Num):
            rest = factors[1:]
            if len(rest) == 1:
                return factors[0].value, rest[0]
            return factors[0].value, Mul(rest)
        return Fraction(1), term
    return Fraction(1), term


def _apply_coeff(c, rest_expr):
    if c == 1:
        return rest_expr
    return mul(num(c), rest_expr)


# ---------------------------------------------------------------------------
# smart Mul
# ---------------------------------------------------------------------------


def mul(*args):
    flat = []
    for a in args:
        a = _coerce(a)
        if isinstance(a, Mul):
            flat.extend(a.factors)
        else:
            flat.append(a)

    coeff = Fraction(1)
    bases = {}
    order = []
    for f in flat:
        if isinstance(f, Num):
            coeff *= f.value
            continue
        base, exp = (f.base, f.exp) if isinstance(f, Pow) else (f, ONE)
        if base not in bases:
            bases[base] = ZERO
            order.append(base)
        bases[base] = add(bases[base], exp)

    if coeff == 0:
        return ZERO

    factors = []
    for base in order:
        e = bases[base]
        if isinstance(e, Num) and e.value == 0:
            continue
        factors.append(power(base, e))
    factors.sort(key=sort_key)

    if coeff != 1 or not factors:
        factors.insert(0, num(coeff))

    if len(factors) == 1:
        return factors[0]
    return Mul(tuple(factors))


# ---------------------------------------------------------------------------
# smart Pow (incl. exact + partial radical extraction)
# ---------------------------------------------------------------------------


def power(base, exp):
    base = _coerce(base)
    exp = _coerce(exp)

    if isinstance(exp, Num):
        if exp.value == 0:
            return ONE
        if exp.value == 1:
            return base

    if isinstance(base, Num):
        if base.value == 0:
            if isinstance(exp, Num):
                if exp.value > 0:
                    return ZERO
                raise DomainError("0 cannot be raised to a non-positive power")
        elif base.value == 1:
            return ONE
        if isinstance(exp, Num):
            result = _num_pow(base.value, exp.value)
            if result is not None:
                return result

    if isinstance(base, Pow) and isinstance(exp, Num) and isinstance(base.exp, Num):
        # (b^p)^q -> b^(p*q); safe here because our exponents are always
        # rational and we don't track branch cuts for this scoped kernel.
        return power(base.base, num(base.exp.value * exp.value))

    if isinstance(base, Mul) and isinstance(exp, Num) and exp.value.denominator == 1:
        # (a*b*...)^n -> a^n * b^n * ... for integer n (always valid).
        return mul(*[power(f, exp) for f in base.factors])

    return Pow(base, exp)


def _num_pow(a: Fraction, p: Fraction):
    """Try to compute a**p exactly as a Fraction, or as coeff*Pow(k, m/n)
    with a perfect-power radical factor partially or fully extracted (e.g.
    8**(1/2) -> 2*sqrt(2)). Returns None if no exact simplification applies
    (the caller then leaves the general Pow node in place)."""
    if p.denominator == 1:
        n = p.numerator
        if n < 0 and a == 0:
            raise DomainError("division by zero")
        return num(a ** n)

    # p = m/n in lowest terms, n > 1.
    m, n = p.numerator, p.denominator
    sign_mult = 1
    if a < 0:
        if n % 2 == 0:
            return None  # even root of a negative number: not real, stays symbolic
        sign_mult = -1 if (m % 2) else 1
        a = -a

    num_outside, num_inside = _extract_root(a.numerator, n)
    den_outside, den_inside = _extract_root(a.denominator, n)

    if num_inside == 1 and den_inside == 1:
        base_val = Fraction(num_outside, den_outside)
        return num(sign_mult * (base_val ** m))

    if num_outside == 1 and den_outside == 1:
        return None  # nothing extractable, don't rebuild an identical node

    coeff = Fraction(num_outside, den_outside) ** m
    leftover = Fraction(num_inside, den_inside)
    radical = power(num(leftover), num(Fraction(m, n)))
    return mul(num(sign_mult * coeff), radical)


def _extract_root(k: int, n: int):
    """Factor k (a nonnegative integer) into (outside, inside) such that
    k == outside**n * inside and `inside` has no remaining perfect-n-th-power
    factor > 1, using trial-division prime factorization. E.g. extract_root(8,2)
    -> (2, 2) since 8 = 2**2 * 2, i.e. sqrt(8) = 2*sqrt(2)."""
    if k == 0:
        return 0, 1
    if k == 1:
        return 1, 1
    outside = 1
    inside = 1
    remaining = k
    d = 2
    while d * d <= remaining:
        if remaining % d == 0:
            count = 0
            while remaining % d == 0:
                remaining //= d
                count += 1
            outside *= d ** (count // n)
            inside *= d ** (count % n)
        d += 1
    if remaining > 1:
        inside *= remaining
    return outside, inside


def iroot(k: int, n: int) -> int:
    """Exact integer floor(k ** (1/n)) for k >= 0, n >= 1, via binary search
    (no floating point, so it's exact for arbitrarily large k)."""
    if k < 0:
        raise ValueError("iroot expects a nonnegative integer")
    if k in (0, 1) or n == 1:
        return k
    lo, hi = 0, 1
    while hi ** n <= k:
        hi *= 2
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if mid ** n <= k:
            lo = mid
        else:
            hi = mid - 1
    return lo


# ---------------------------------------------------------------------------
# tree walking helpers
# ---------------------------------------------------------------------------


def _collect_symbols(e, out):
    if isinstance(e, Symbol):
        out.add(e)
    else:
        for a in e.args:
            _collect_symbols(a, out)


def _subs(e, mapping):
    if isinstance(e, Symbol):
        return mapping.get(e.name, e)
    if isinstance(e, Num):
        return e
    if isinstance(e, Add):
        return add(*[_subs(t, mapping) for t in e.terms])
    if isinstance(e, Mul):
        return mul(*[_subs(f, mapping) for f in e.factors])
    if isinstance(e, Pow):
        return power(_subs(e.base, mapping), _subs(e.exp, mapping))
    if isinstance(e, Func):
        return func(e.name, _subs(e.arg, mapping))
    raise TypeError(type(e))


_CMATH_FUNCS = {
    "sin": cmath.sin, "cos": cmath.cos, "tan": cmath.tan,
    "exp": cmath.exp, "sqrt": cmath.sqrt,
    "asin": cmath.asin, "acos": cmath.acos, "atan": cmath.atan,
    "sinh": cmath.sinh, "cosh": cmath.cosh, "tanh": cmath.tanh,
}


def _evalf(e, bindings):
    if isinstance(e, Num):
        return complex(e.value)
    if isinstance(e, Symbol):
        if e.name not in bindings:
            raise DomainError(f"free symbol '{e.name}' has no numeric binding")
        return bindings[e.name]
    if isinstance(e, Add):
        return sum((_evalf(t, bindings) for t in e.terms), complex(0))
    if isinstance(e, Mul):
        result = complex(1)
        for f in e.factors:
            result *= _evalf(f, bindings)
        return result
    if isinstance(e, Pow):
        b = _evalf(e.base, bindings)
        p = _evalf(e.exp, bindings)
        if b == 0 and p.real < 0:
            raise DomainError("division by zero (0 raised to a negative power)")
        return b ** p
    if isinstance(e, Func):
        a = _evalf(e.arg, bindings)
        if e.name == "log":
            if a == 0:
                raise DomainError("log(0) is undefined")
            return cmath.log(a)
        if e.name == "abs":
            return complex(abs(a))
        return _CMATH_FUNCS[e.name](a)
    raise TypeError(type(e))


# ---------------------------------------------------------------------------
# human-readable printing
# ---------------------------------------------------------------------------

_PRECEDENCE = {"add": 1, "mul": 2, "unary": 3, "pow": 4, "atom": 5}


def to_str(e, parent_prec=0, pow_ctx=None):
    if isinstance(e, Num):
        v = e.value
        if v.denominator == 1:
            s = str(v.numerator)
        else:
            s = f"{v.numerator}/{v.denominator}"
        # Parens are only actually required around a Num in two situations,
        # both because our own grammar's exponent slot binds tighter than
        # '/' or unary '-' bind on the *outside* of a '^':
        #  - a negative Pow *base*: "(-2)^2" (=4) parses differently from
        #    our own parser's "-2^2" (=-4, unary minus binds looser than ^).
        #  - a fractional Pow *exponent*: "2^1/2" parses as (2^1)/2 = 1, not
        #    2^(1/2) — the exponent slot only ever consumes one unary/power
        #    chain, never a following '/'.
        # Elsewhere ("-2*x", "x + -2", handled by the Add printer below) a
        # bare negative or fractional number round-trips fine unparenthesized.
        if (pow_ctx == "base" and v < 0) or (pow_ctx == "exp" and v.denominator != 1):
            return f"({s})"
        return s
    if isinstance(e, Symbol):
        return e.name
    if isinstance(e, Func):
        return f"{e.name}({to_str(e.arg)})"
    if isinstance(e, Pow):
        base_s = to_str(e.base, _PRECEDENCE["pow"] + 1, pow_ctx="base")
        exp_s = to_str(e.exp, _PRECEDENCE["pow"] + 1, pow_ctx="exp")
        s = f"{base_s}^{exp_s}"
        return f"({s})" if parent_prec > _PRECEDENCE["pow"] else s
    if isinstance(e, Mul):
        num_factors, den_factors = [], []
        for f in e.factors:
            if isinstance(f, Pow) and isinstance(f.exp, Num) and f.exp.value < 0:
                den_factors.append(power(f.base, num(-f.exp.value)))
            else:
                num_factors.append(f)
        if den_factors:
            num_s = _mul_str(num_factors) if num_factors else "1"
            den_s = _mul_str(den_factors)
            paren_den = len(den_factors) > 1
            s = f"{num_s}/{('(' + den_s + ')') if paren_den else den_s}"
        else:
            s = _mul_str(num_factors)
        return f"({s})" if parent_prec > _PRECEDENCE["mul"] else s
    if isinstance(e, Add):
        parts = []
        for i, t in enumerate(e.terms):
            s = to_str(t, _PRECEDENCE["add"] + 1)
            if i == 0:
                parts.append(s)
            elif s.startswith("-"):
                parts.append(f" - {s[1:]}")
            else:
                parts.append(f" + {s}")
        s = "".join(parts)
        return f"({s})" if parent_prec > _PRECEDENCE["add"] else s
    raise TypeError(type(e))


def _mul_str(factors):
    if not factors:
        return "1"
    if len(factors) == 1:
        return to_str(factors[0], _PRECEDENCE["mul"] + 1)
    if isinstance(factors[0], Num) and factors[0].value == -1:
        rest = _mul_str(list(factors[1:]))
        return f"-{rest}"
    parts = [to_str(f, _PRECEDENCE["mul"] + 1) for f in factors]
    return "*".join(parts)
