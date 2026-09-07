"""Leibniz expression tree.

Every expression is an immutable, hashable node. Arithmetic operators are
overloaded so expressions build with ordinary Python syntax (``x + 1``,
``2 * x ** 3``), and the smart constructors ``add``/``mul``/``pow_`` keep the
tree in a canonical, already-simplified-as-far-as-possible form as it is
built (flattened, constants folded exactly over ``Fraction``, like terms and
like powers combined). ``simplify.py`` layers additional normalization
(trig/log special values, rational-function cancellation) on top of this.

No floating point ever appears in exact arithmetic: numeric coefficients are
``fractions.Fraction``. The only floats in this module live behind
``Constant.value`` (used solely by ``evalf`` for numeric sampling) and inside
``evalf`` itself.
"""

from __future__ import annotations

from fractions import Fraction
import math


def F(x) -> Fraction:
    """Coerce an int/Fraction/float-that-is-exact into a Fraction."""
    if isinstance(x, Fraction):
        return x
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, float):
        if x != x or x in (float("inf"), float("-inf")):
            raise ValueError(f"cannot represent {x!r} exactly")
        return Fraction(x).limit_denominator(10**9)
    raise TypeError(f"cannot coerce {x!r} to Fraction")


class Expr:
    """Base class for every node. Subclasses must be hashable and define
    a ``_key`` tuple used for structural equality/ordering."""

    __slots__ = ()

    # -- operator overloads -------------------------------------------------
    def __add__(self, other):
        return add(self, _wrap(other))

    def __radd__(self, other):
        return add(_wrap(other), self)

    def __sub__(self, other):
        return add(self, mul(Num(-1), _wrap(other)))

    def __rsub__(self, other):
        return add(_wrap(other), mul(Num(-1), self))

    def __mul__(self, other):
        return mul(self, _wrap(other))

    def __rmul__(self, other):
        return mul(_wrap(other), self)

    def __truediv__(self, other):
        return mul(self, pow_(_wrap(other), Num(-1)))

    def __rtruediv__(self, other):
        return mul(_wrap(other), pow_(self, Num(-1)))

    def __neg__(self):
        return mul(Num(-1), self)

    def __pow__(self, other):
        return pow_(self, _wrap(other))

    def __rpow__(self, other):
        return pow_(_wrap(other), self)

    # -- structural identity -------------------------------------------------
    def _key(self):
        raise NotImplementedError

    def __eq__(self, other):
        if not isinstance(other, Expr):
            return NotImplemented
        return type(self) is type(other) and self._key() == other._key()

    def __hash__(self):
        return hash((type(self).__name__, self._key()))

    def __repr__(self):
        from .render import to_str

        return to_str(self)


class Num(Expr):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value: Fraction = F(value)

    def _key(self):
        return (self.value,)


class Symbol(Expr):
    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def _key(self):
        return (self.name,)


class Constant(Symbol):
    """A named symbolic constant (pi, e) with a known float value, used only
    for numeric evaluation. Algebraically it behaves like any other atomic
    symbol (Pi + Pi -> 2*Pi), it just also knows what it equals numerically.
    """

    __slots__ = ("value",)

    def __init__(self, name: str, value: float):
        super().__init__(name)
        self.value = value


class Imaginary(Symbol):
    """The imaginary unit i. Kept as a distinguished atomic symbol so that
    Mul/Pow combining can special-case i**2 == -1 (see ``mul``/``pow_``)."""

    __slots__ = ()

    def __init__(self):
        super().__init__("i")


PI = Constant("pi", math.pi)
E = Constant("e", math.e)
I = Imaginary()

FUNC_NAMES = ("sin", "cos", "tan", "exp", "ln", "sqrt", "abs")


class Func(Expr):
    __slots__ = ("name", "arg")

    def __init__(self, name: str, arg: Expr):
        if name not in FUNC_NAMES:
            raise ValueError(f"unknown function {name!r}")
        self.name = name
        self.arg = arg

    def _key(self):
        return (self.name, self.arg)


class Add(Expr):
    __slots__ = ("args",)

    def __init__(self, args: tuple):
        self.args = args

    def _key(self):
        return self.args


class Mul(Expr):
    __slots__ = ("args",)

    def __init__(self, args: tuple):
        self.args = args

    def _key(self):
        return self.args


class Pow(Expr):
    __slots__ = ("base", "exp")

    def __init__(self, base: Expr, exp: Expr):
        self.base = base
        self.exp = exp

    def _key(self):
        return (self.base, self.exp)


def _wrap(x) -> Expr:
    if isinstance(x, Expr):
        return x
    if isinstance(x, (int, Fraction)):
        return Num(x)
    raise TypeError(f"cannot use {x!r} in an expression")


# ---------------------------------------------------------------------------
# Canonical ordering. Not required to be "pretty", only total and stable, so
# that structurally-equal expressions are always built the same way (needed
# for equality checks and for dict/set use of expressions as keys elsewhere).
# ---------------------------------------------------------------------------

_TYPE_RANK = {Num: 0, Imaginary: 1, Constant: 2, Symbol: 3, Func: 4, Pow: 5, Mul: 6, Add: 7}


def _type_rank(e: Expr) -> int:
    for cls, rank in _TYPE_RANK.items():
        if type(e) is cls:
            return rank
    return 99


def _sort_key(e: Expr):
    from .render import to_str

    return (_type_rank(e), to_str(e))


def _factor_degree(f: Expr) -> Fraction:
    """Heuristic total degree of a single multiplicative factor, used only
    to order Add's terms (highest degree first) for readable output."""
    if isinstance(f, Num):
        return Fraction(0)
    if isinstance(f, Pow) and isinstance(f.exp, Num):
        return f.exp.value
    return Fraction(1)


def _term_degree(term: Expr) -> Fraction:
    if isinstance(term, Mul):
        return sum((_factor_degree(f) for f in term.args), Fraction(0))
    return _factor_degree(term)


def _term_is_negative(term: Expr) -> bool:
    if isinstance(term, Num):
        return term.value < 0
    if isinstance(term, Mul) and isinstance(term.args[0], Num):
        return term.args[0].value < 0
    return False


def _add_sort_key(term: Expr):
    from .render import to_str

    # same degree -> positive-looking terms before negative ones (so "x - i"
    # prints as "x - i", not "-i + x"), then alphabetical for determinism
    return (-_term_degree(term), _term_is_negative(term), to_str(term))


# ---------------------------------------------------------------------------
# Smart constructors
# ---------------------------------------------------------------------------


def add(*terms: Expr) -> Expr:
    """Build a simplified sum: flatten nested Add, fold Num terms exactly,
    and combine like non-numeric terms (3*x + 2*x -> 5*x)."""
    flat: list[Expr] = []
    for t in terms:
        t = _wrap(t)
        if isinstance(t, Add):
            flat.extend(t.args)
        else:
            flat.append(t)

    const_sum = Fraction(0)
    # map canonical "rest" repr -> (coeff Fraction, rest Expr)
    buckets: dict = {}
    order: list = []
    for t in flat:
        if isinstance(t, Num):
            const_sum += t.value
            continue
        coeff, rest = _split_coeff(t)
        key = rest._key(), type(rest).__name__
        if key in buckets:
            buckets[key] = (buckets[key][0] + coeff, rest)
        else:
            buckets[key] = (coeff, rest)
            order.append(key)

    out_terms: list[Expr] = []
    for key in order:
        coeff, rest = buckets[key]
        if coeff == 0:
            continue
        if coeff == 1:
            out_terms.append(rest)
        else:
            # rest may be a raw (unflattened) Mul from _split_coeff below;
            # go through mul() rather than a bare Mul(...) so a term like
            # coeff*(i*sqrt(19)) doesn't end up as a Mul nested inside a
            # Mul, which would later hide i and sqrt(19) from mul()'s own
            # same-base combining if this term gets multiplied again.
            out_terms.append(mul(Num(coeff), rest))

    out_terms.sort(key=_add_sort_key)

    if const_sum != 0 or not out_terms:
        out_terms.append(Num(const_sum))

    if len(out_terms) == 1:
        return out_terms[0]
    return Add(tuple(out_terms))


def _split_coeff(t: Expr):
    """Split a term into (numeric coefficient, remaining expr)."""
    if isinstance(t, Mul):
        num_part = Fraction(1)
        rest_factors = []
        for f in t.args:
            if isinstance(f, Num):
                num_part *= f.value
            else:
                rest_factors.append(f)
        if not rest_factors:
            return num_part, Num(1)
        if len(rest_factors) == 1:
            return num_part, rest_factors[0]
        return num_part, Mul(tuple(rest_factors))
    return Fraction(1), t


def _flatten_mul(f: Expr):
    """Fully flatten nested Muls (any depth), not just one level -- a
    defensive measure so mul()'s same-base combining never misses an atom
    hidden inside a Mul-within-a-Mul, however that structure was built."""
    if isinstance(f, Mul):
        for sub in f.args:
            yield from _flatten_mul(sub)
    else:
        yield f


def _distribute_pair(a: Expr, b: Expr) -> Expr:
    a_terms = a.args if isinstance(a, Add) else (a,)
    b_terms = b.args if isinstance(b, Add) else (b,)
    return add(*[mul(ta, tb) for ta in a_terms for tb in b_terms])


def mul(*factors: Expr) -> Expr:
    """Build a simplified product: flatten nested Mul, fold Num factors
    exactly, combine powers of identical bases (x*x -> x**2), reduce powers
    of the imaginary unit modulo 4, and fully distribute over every Add
    factor still present (so multiplication is always as eager as addition).
    """
    flat: list[Expr] = []
    for f in factors:
        flat.extend(_flatten_mul(_wrap(f)))

    num_coeff = Fraction(1)
    # base._key()/type -> (base, exponent Expr-built-additively-when-Num)
    bases: dict = {}
    order: list = []
    add_factor = None
    other_factors_for_add: list[Expr] = []

    for f in flat:
        if isinstance(f, Num):
            if f.value == 0:
                return Num(0)
            num_coeff *= f.value
            continue
        base, exp = (f.base, f.exp) if isinstance(f, Pow) else (f, Num(1))
        key = base._key(), type(base).__name__
        if key in bases:
            prev_base, prev_exp = bases[key]
            bases[key] = (prev_base, add(prev_exp, exp))
        else:
            bases[key] = (base, exp)
            order.append(key)

    out_factors: list[Expr] = []
    for key in order:
        base, exp = bases[key]
        # pow_() folds i**n (mod-4 cycle), sqrt(u)**n, and (f1*f2*...)**n
        # on its own now, so no special-casing is needed here any more.
        p = pow_(base, exp)
        if isinstance(p, Num):
            num_coeff *= p.value
        elif isinstance(p, Mul):
            # pow_ can itself return a Mul (e.g. from folding); re-flatten
            for pf in p.args:
                if isinstance(pf, Num):
                    num_coeff *= pf.value
                else:
                    out_factors.append(pf)
        else:
            out_factors.append(p)

    if num_coeff == 0:
        return Num(0)

    # Fully distribute whenever any Add factor remains, so multiplication is
    # always as eager as addition (mul() never leaves "2*(x+1)" any more
    # un-distributed than add() would leave "x + x" un-combined) -- a single
    # scalar times one Add and a product of several Adds are both expanded
    # the same way, instead of the former auto-expanding and the latter
    # silently staying factored. `factor()` deliberately builds its
    # (intentionally-factored) result through the raw Mul/Add constructors,
    # bypassing this, rather than asking mul() to hold something back.
    if any(isinstance(f, Add) for f in out_factors):
        result: Expr = Num(num_coeff)
        for f in out_factors:
            result = _distribute_pair(result, f)
        return result

    out_factors.sort(key=_sort_key)

    if num_coeff != 1 or not out_factors:
        out_factors.insert(0, Num(num_coeff))

    if len(out_factors) == 1:
        return out_factors[0]
    return Mul(tuple(out_factors))


def pow_(base: Expr, exp: Expr) -> Expr:
    base = _wrap(base)
    exp = _wrap(exp)

    if isinstance(exp, Num):
        if exp.value == 0:
            return Num(1)
        if exp.value == 1:
            return base

    if isinstance(base, Func) and base.name == "sqrt" and isinstance(exp, Num) and exp.value.denominator == 1:
        # rationalize an integer power of sqrt(u): sqrt(u)**n = u**(n//2) * (sqrt(u) if n odd)
        # (Python's divmod floors, so this is exact for negative n too)
        half, remainder = divmod(exp.value.numerator, 2)
        result = pow_(base.arg, Num(half))
        return mul(result, base) if remainder else result

    if isinstance(base, Imaginary) and isinstance(exp, Num) and exp.value.denominator == 1:
        # i**n cycles with period 4; Python's % always returns 0..3 here,
        # even for negative n, so this is exact for negative powers too
        return (Num(1), base, Num(-1), mul(Num(-1), base))[exp.value.numerator % 4]

    if isinstance(base, Mul) and isinstance(exp, Num) and exp.value.denominator == 1:
        # (f1*f2*...)**n = f1**n * f2**n * ... -- exact for any integer n,
        # positive or negative, with no branch-cut ambiguity (unlike a
        # fractional exponent, integer powers are just repeated
        # multiplication, so this can never change the value)
        return mul(*[pow_(f, exp) for f in base.args])

    if isinstance(base, Num):
        if base.value == 0:
            if isinstance(exp, Num):
                if exp.value > 0:
                    return Num(0)
                raise ZeroDivisionError("0 cannot be raised to a non-positive power")
        elif base.value == 1:
            return Num(1)
        elif isinstance(exp, Num):
            v = _exact_pow(base.value, exp.value)
            if v is not None:
                return Num(v) if isinstance(v, Fraction) else v

    if isinstance(base, Pow) and isinstance(exp, Num) and isinstance(base.exp, Num):
        return pow_(base.base, Num(base.exp.value * exp.value))

    return Pow(base, exp)


def _isqrt_exact(v: Fraction):
    """Exact sqrt of a non-negative Fraction if it's a perfect square of a
    rational, else None."""
    if v < 0:
        return None
    n, d = v.numerator, v.denominator
    rn, rd = math.isqrt(n), math.isqrt(d)
    if rn * rn == n and rd * rd == d:
        return Fraction(rn, rd)
    return None


def _square_free_split(m: int):
    """m = k*k*r with r square-free (m, k, r >= 0)."""
    if m == 0:
        return 0, 0
    k, r, i = 1, m, 2
    while i * i <= r:
        while r % (i * i) == 0:
            r //= i * i
            k *= i
        i += 1
    return k, r


def _extract_square_factor(v: Fraction):
    """For a non-negative Fraction v with no exact sqrt, split v = k*k*r
    with r minimal (square-free numerator and denominator). Returns
    (k, r) as Fractions; k == 1 means v was already square-free."""
    kn, rn = _square_free_split(v.numerator)
    kd, rd = _square_free_split(v.denominator)
    return Fraction(kn, kd), Fraction(rn, rd)


def func_(name: str, arg: Expr) -> Expr:
    """Smart constructor for Func: folds special/exact values so that, e.g.,
    sin(0), cos(0), exp(0), ln(1), sqrt(4) and sqrt(-4) all reduce fully
    instead of staying as inert Func nodes."""
    arg = _wrap(arg)

    if isinstance(arg, Num):
        v = arg.value
        if name == "sin" and v == 0:
            return Num(0)
        if name == "cos" and v == 0:
            return Num(1)
        if name == "tan" and v == 0:
            return Num(0)
        if name == "exp" and v == 0:
            return Num(1)
        if name == "ln" and v == 1:
            return Num(0)
        if name == "abs":
            return Num(abs(v))
        if name == "sqrt":
            if v == 0:
                return Num(0)
            if v < 0:
                # recurse (not a raw Func) so a non-perfect-square magnitude
                # still gets its largest square factor extracted, e.g.
                # sqrt(-8) -> 2*i*sqrt(2), not i*sqrt(8)
                return mul(I, func_("sqrt", Num(-v)))
            exact = _isqrt_exact(v)
            if exact is not None:
                return Num(exact)
            k, r = _extract_square_factor(v)
            if k != 1:
                return mul(Num(k), Func("sqrt", Num(r)))

    if name == "exp" and isinstance(arg, Func) and arg.name == "ln":
        return arg.arg
    if name == "ln" and isinstance(arg, Func) and arg.name == "exp":
        return arg.arg

    if name in ("sin", "tan") and isinstance(arg, Mul) and isinstance(arg.args[0], Num) and arg.args[0].value < 0:
        return mul(Num(-1), Func(name, mul(*([Num(-arg.args[0].value)] + list(arg.args[1:])))))
    if name == "cos" and isinstance(arg, Mul) and isinstance(arg.args[0], Num) and arg.args[0].value < 0:
        return Func(name, mul(*([Num(-arg.args[0].value)] + list(arg.args[1:]))))

    return Func(name, arg)


def _exact_pow(base: Fraction, exp: Fraction):
    """Return an exact Fraction for base**exp when representable, else None
    to leave the Pow node symbolic (irrational, e.g. 2**(1/2))."""
    if exp.denominator == 1:
        n = exp.numerator
        if n >= 0:
            return base**n
        if base == 0:
            raise ZeroDivisionError("0 cannot be raised to a negative power")
        return Fraction(1) / (base**(-n))
    return None


# ---------------------------------------------------------------------------
# Utilities used throughout the rest of the package
# ---------------------------------------------------------------------------


def is_zero(e: Expr) -> bool:
    return isinstance(e, Num) and e.value == 0


def is_one(e: Expr) -> bool:
    return isinstance(e, Num) and e.value == 1


def is_number(e: Expr) -> bool:
    return isinstance(e, Num)


def free_symbols(e: Expr) -> set:
    """Names of ordinary (non-constant, non-imaginary) Symbols in e."""
    out = set()

    def walk(node):
        if isinstance(node, (Constant, Imaginary)):
            return
        if isinstance(node, Symbol):
            out.add(node.name)
        elif isinstance(node, Func):
            walk(node.arg)
        elif isinstance(node, Pow):
            walk(node.base)
            walk(node.exp)
        elif isinstance(node, (Add, Mul)):
            for a in node.args:
                walk(a)

    walk(e)
    return out


def subs(e: Expr, mapping: dict) -> Expr:
    """Substitute Symbol(name) -> replacement Expr for each name in mapping
    (mapping values are coerced to Expr). Rebuilt through the smart
    constructors, so the result comes back canonicalized."""
    mapping = {k: _wrap(v) for k, v in mapping.items()}

    def walk(node):
        if isinstance(node, (Constant, Imaginary)):
            return node
        if isinstance(node, Symbol):
            return mapping.get(node.name, node)
        if isinstance(node, Num):
            return node
        if isinstance(node, Func):
            return Func(node.name, walk(node.arg))
        if isinstance(node, Pow):
            return pow_(walk(node.base), walk(node.exp))
        if isinstance(node, Add):
            return add(*[walk(a) for a in node.args])
        if isinstance(node, Mul):
            return mul(*[walk(a) for a in node.args])
        raise TypeError(type(node))

    return walk(e)


class CannotEvaluate(Exception):
    pass


_FUNC_NUMERIC = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "exp": math.exp,
    "ln": lambda x: math.log(x) if not isinstance(x, complex) and x > 0 else complex(x).__abs__(),
    "sqrt": lambda x: x**0.5 if isinstance(x, complex) or x >= 0 else complex(x) ** 0.5,
    "abs": abs,
}


def evalf(e: Expr, mapping: dict | None = None):
    """Numeric evaluation to a Python float or complex. Raises
    CannotEvaluate if a free symbol has no binding in `mapping`."""
    mapping = mapping or {}

    def walk(node):
        if isinstance(node, Num):
            return float(node.value)
        if isinstance(node, Imaginary):
            return complex(0, 1)
        if isinstance(node, Constant):
            return node.value
        if isinstance(node, Symbol):
            if node.name not in mapping:
                raise CannotEvaluate(f"no value given for '{node.name}'")
            return mapping[node.name]
        if isinstance(node, Func):
            arg = walk(node.arg)
            if node.name == "ln" and (isinstance(arg, complex) or arg <= 0):
                import cmath

                return cmath.log(arg)
            if node.name == "sqrt" and (isinstance(arg, complex) or arg < 0):
                import cmath

                return cmath.sqrt(arg)
            return _FUNC_NUMERIC[node.name](arg)
        if isinstance(node, Pow):
            b, ex = walk(node.base), walk(node.exp)
            try:
                return b**ex
            except (ValueError, ZeroDivisionError):
                return complex(b) ** ex
        if isinstance(node, Add):
            return sum(walk(a) for a in node.args)
        if isinstance(node, Mul):
            out = 1
            for a in node.args:
                out *= walk(a)
            return out
        raise TypeError(type(node))

    result = walk(e)
    if isinstance(result, complex) and abs(result.imag) < 1e-9:
        result = result.real
    return result
