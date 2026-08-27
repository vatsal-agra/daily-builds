"""Arithmetic expression evaluator, shared by the golden model and (via
term reification) the WAM's `is/2` and comparison builtins."""
import math
from .terms import Atom, Num, Struct, Var, deref
from .errors import type_error, instantiation_error, evaluation_error


def _int_div(a, b):
    if b == 0:
        raise evaluation_error("zero_divisor")
    q = a // b
    if (a % b != 0) and ((a < 0) != (b < 0)):
        pass  # floor division; `//` in Prolog is floor div, matches Python
    return q


def _trunc_div(a, b):
    if b == 0:
        raise evaluation_error("zero_divisor")
    q = a / b
    return int(q) if q >= 0 else -int(-q)


_BINOPS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: (_true_div(a, b)),
    "//": lambda a, b: _int_div(int(a), int(b)),
    "div": lambda a, b: _int_div(int(a), int(b)),
    "mod": lambda a, b: _pl_mod(a, b),
    "rem": lambda a, b: _pl_rem(a, b),
    "**": lambda a, b: math.pow(a, b),
    "^": lambda a, b: _pow_int_preserving(a, b),
    "min": lambda a, b: min(a, b),
    "max": lambda a, b: max(a, b),
    ">>": lambda a, b: int(a) >> int(b),
    "<<": lambda a, b: int(a) << int(b),
    "/\\": lambda a, b: int(a) & int(b),
    "\\/": lambda a, b: int(a) | int(b),
    "xor": lambda a, b: int(a) ^ int(b),
    "atan2": lambda a, b: math.atan2(a, b),
    "atan": lambda a, b: math.atan2(a, b),
    "gcd": lambda a, b: math.gcd(int(a), int(b)),
    "copysign": lambda a, b: math.copysign(a, b),
    "truncate": lambda a, b: _trunc_div(a, b),
}

_UNOPS = {
    "-": lambda a: -a,
    "+": lambda a: a,
    "abs": lambda a: abs(a),
    "sign": lambda a: (0 if a == 0 else (1 if a > 0 else -1)) if isinstance(a, int) else math.copysign(1.0, a) if a != 0 else 0.0,
    "sqrt": lambda a: math.sqrt(a),
    "sin": lambda a: math.sin(a),
    "cos": lambda a: math.cos(a),
    "tan": lambda a: math.tan(a),
    "asin": lambda a: math.asin(a),
    "acos": lambda a: math.acos(a),
    "atan": lambda a: math.atan(a),
    "exp": lambda a: math.exp(a),
    "log": lambda a: math.log(a),
    "log2": lambda a: math.log2(a),
    "float": lambda a: float(a),
    "integer": lambda a: int(round(a)),
    "floor": lambda a: math.floor(a),
    "ceiling": lambda a: math.ceil(a),
    "round": lambda a: math.floor(a + 0.5) if isinstance(a, float) else a,
    "truncate": lambda a: math.trunc(a),
    "float_integer_part": lambda a: float(math.trunc(a)),
    "float_fractional_part": lambda a: a - math.trunc(a),
    "\\": lambda a: ~int(a),
    "msb": lambda a: int(a).bit_length() - 1,
    "succ": lambda a: a + 1,
}

_CONSTS = {
    "pi": math.pi, "e": math.e, "inf": math.inf, "nan": math.nan,
    "epsilon": 2.220446049250313e-16, "max_tagged_integer": 2**60,
    "random": None,  # handled specially
}


def _true_div(a, b):
    if b == 0:
        raise evaluation_error("zero_divisor")
    if isinstance(a, int) and isinstance(b, int) and a % b == 0:
        return a // b
    return a / b


def _pl_mod(a, b):
    if b == 0:
        raise evaluation_error("zero_divisor")
    return a - (a // b) * b


def _pl_rem(a, b):
    if b == 0:
        raise evaluation_error("zero_divisor")
    return a - _trunc_div(a, b) * b


def _pow_int_preserving(a, b):
    if isinstance(a, int) and isinstance(b, int) and b >= 0:
        return a ** b
    return math.pow(a, b)


def eval_arith(term):
    """Evaluate a ground(-ish) arithmetic expression Term to a Python
    int/float. Raises PrologError subclasses on malformed input."""
    t = deref(term)
    if isinstance(t, Num):
        return t.value
    if isinstance(t, Var):
        raise instantiation_error()
    if isinstance(t, Atom):
        if t.name == "random":
            import random
            return random.random()
        if t.name in _CONSTS:
            return _CONSTS[t.name]
        raise type_error("evaluable", Struct("/", (t, Num(0))))
    if isinstance(t, Struct):
        if t.arity == 1:
            if t.name == "random" and t.arity == 1:
                pass
            fn = _UNOPS.get(t.name)
            if fn is None:
                raise type_error("evaluable", Struct("/", (Atom(t.name), Num(1))))
            return fn(eval_arith(t.args[0]))
        if t.arity == 2:
            if t.name == "random":
                import random
                return random.randrange(int(eval_arith(t.args[0])), int(eval_arith(t.args[1])))
            fn = _BINOPS.get(t.name)
            if fn is None:
                raise type_error("evaluable", Struct("/", (Atom(t.name), Num(2))))
            return fn(eval_arith(t.args[0]), eval_arith(t.args[1]))
    raise type_error("evaluable", t)


def compare_arith(op, a, b):
    x, y = eval_arith(a), eval_arith(b)
    return {"<": x < y, ">": x > y, "=<": x <= y, ">=": x >= y,
            "=:=": x == y, "=\\=": x != y}[op]
