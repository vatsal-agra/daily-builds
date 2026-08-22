"""Arithmetic expression evaluation for is/2 and the comparison operators."""

import math

from .errors import HornError
from .terms import Atom, Compound, Number, Var, deref

_CONST = {"pi": math.pi, "e": math.e, "inf": math.inf, "nan": math.nan}

_BINARY = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "min": min,
    "max": max,
    "**": lambda a, b: a**b,
    "^": lambda a, b: a**b,
}


def eval_arith(term):
    t = deref(term)
    if isinstance(t, Number):
        return t.value
    if isinstance(t, Var):
        raise HornError("instantiation_error: arithmetic expression has an unbound variable")
    if isinstance(t, Atom):
        if t.name in _CONST:
            return _CONST[t.name]
        raise HornError(f"type_error: '{t.name}' is not an evaluable atom")
    if isinstance(t, Compound):
        args = [eval_arith(a) for a in t.args]
        f = t.functor
        if len(args) == 2:
            a, b = args
            if f in _BINARY:
                return _BINARY[f](a, b)
            if f == "/":
                if b == 0:
                    raise HornError("evaluation_error: zero_divisor")
                r = a / b
                if isinstance(a, int) and isinstance(b, int) and a % b == 0:
                    return a // b
                return r
            if f == "//":
                if b == 0:
                    raise HornError("evaluation_error: zero_divisor")
                return a // b  # floor division, like Python's //
            if f in ("mod",):
                if b == 0:
                    raise HornError("evaluation_error: zero_divisor")
                return a % b
            if f == "rem":
                if b == 0:
                    raise HornError("evaluation_error: zero_divisor")
                return int(math.fmod(a, b))
        elif len(args) == 1:
            (a,) = args
            if f == "-":
                return -a
            if f == "+":
                return a
            if f == "abs":
                return abs(a)
            if f == "sign":
                return (a > 0) - (a < 0)
            if f == "sqrt":
                return math.sqrt(a)
            if f == "float":
                return float(a)
            if f == "truncate":
                return int(a)
            if f == "round":
                return round(a)
        raise HornError(f"type_error: '{f}/{len(args)}' is not an evaluable functor")
    raise HornError(f"type_error: cannot evaluate {t!r} as arithmetic")
