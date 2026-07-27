"""A tree-walking evaluator over the same AST the type checker consumes.

Only ever invoked on programs that already passed `infer_program` — so
there is no type dispatch, no casts, and (almost) no runtime type errors:
a well-typed program cannot go wrong. The exceptions are the handful of
things HM does not track — division by zero, non-exhaustive matches (this
toy language does no exhaustiveness checking), and comparing function
values (no typeclass/`Ord` constraint) — each raised as a clear EvalError
rather than a raw Python exception.
"""

import operator
from dataclasses import dataclass

from . import nodes as N


class EvalError(Exception):
    def __init__(self, message, span=None):
        super().__init__(message)
        self.message = message
        self.span = span


@dataclass
class Closure:
    param: str
    body: object
    env: dict


@dataclass(frozen=True)
class SomeV:
    value: object


class NoneV:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __eq__(self, other):
        return isinstance(other, NoneV)

    def __hash__(self):
        return hash("NoneV")

    def __repr__(self):
        return "None"


NONE_V = NoneV()


COMPARE_OPS = {
    "=": operator.eq, "<>": operator.ne,
    "<": operator.lt, ">": operator.gt,
    "<=": operator.le, ">=": operator.ge,
}


def _trunc_div(a, b):
    q = a // b
    if (a % b != 0) and ((a < 0) != (b < 0)):
        q += 1
    return q


def eval_expr(env, expr):
    method = _DISPATCH.get(type(expr))
    if method is None:
        raise EvalError(f"internal error: no eval rule for {type(expr).__name__}", expr.span)
    return method(env, expr)


def _eval_Int(env, expr):
    return expr.value


def _eval_Bool(env, expr):
    return expr.value


def _eval_Str(env, expr):
    return expr.value


def _eval_Var(env, expr):
    if expr.name not in env:
        raise EvalError(f"unbound variable '{expr.name}'", expr.span)
    return env[expr.name]


def _eval_TupleExpr(env, expr):
    return tuple(eval_expr(env, item) for item in expr.items)


def _eval_Nil(env, expr):
    return []


def _eval_Cons(env, expr):
    head = eval_expr(env, expr.head)
    tail = eval_expr(env, expr.tail)
    if not isinstance(tail, list):
        raise EvalError("cons tail did not evaluate to a list", expr.span)
    return [head] + tail


def _eval_SomeExpr(env, expr):
    return SomeV(eval_expr(env, expr.value))


def _eval_NoneExpr(env, expr):
    return NONE_V


def _eval_If(env, expr):
    if eval_expr(env, expr.cond):
        return eval_expr(env, expr.then_branch)
    return eval_expr(env, expr.else_branch)


def _eval_Fun(env, expr):
    return Closure(expr.param, expr.body, env)


def _eval_App(env, expr):
    fn = eval_expr(env, expr.fn)
    arg = eval_expr(env, expr.arg)
    if not isinstance(fn, Closure):
        raise EvalError("attempted to call a non-function value", expr.span)
    env2 = dict(fn.env)
    env2[fn.param] = arg
    return eval_expr(env2, fn.body)


def eval_binding(env, name, value_expr, is_rec):
    """Evaluate a `let [rec] name = value_expr` binding on its own.

    Returns the bound value. Shared by the Let/LetRec AST handlers below
    and by the REPL's top-level statement handling (`eval_toplevel`),
    which needs the same self-reference trick without an enclosing
    `in body`.
    """
    if is_rec:
        env_rec = dict(env)
        value = eval_expr(env_rec, value_expr)
        env_rec[name] = value  # safe: value is a Closure capturing this same dict by reference
        return value
    return eval_expr(env, value_expr)


def _eval_Let(env, expr):
    value = eval_binding(env, expr.name, expr.value, is_rec=False)
    env2 = dict(env)
    env2[expr.name] = value
    return eval_expr(env2, expr.body)


def _eval_LetRec(env, expr):
    value = eval_binding(env, expr.name, expr.value, is_rec=True)
    env2 = dict(env)
    env2[expr.name] = value
    return eval_expr(env2, expr.body)


def _eval_BinOp(env, expr):
    op = expr.op
    if op == "&&":
        lv = eval_expr(env, expr.left)
        return lv and eval_expr(env, expr.right)  # short-circuit: don't evaluate right if lv is False
    if op == "||":
        lv = eval_expr(env, expr.left)
        return lv or eval_expr(env, expr.right)  # short-circuit: don't evaluate right if lv is True

    lv = eval_expr(env, expr.left)
    rv = eval_expr(env, expr.right)
    if op == "+":
        return lv + rv
    if op == "-":
        return lv - rv
    if op == "*":
        return lv * rv
    if op == "/":
        if rv == 0:
            raise EvalError("division by zero", expr.right.span)
        return _trunc_div(lv, rv)
    if op in COMPARE_OPS:
        # No typeclass/Ord constraint in this type system, so 'a -> 'a -> bool
        # can be instantiated at function types too. Closures have no
        # meaningful equality (dataclass equality would silently compare
        # captured environments instead of erroring), so reject explicitly
        # rather than let Python's `==`/`!=` return a nonsense answer.
        if _contains_closure(lv) or _contains_closure(rv):
            raise EvalError(f"values of this type cannot be compared with '{op}'", expr.span)
        try:
            return COMPARE_OPS[op](lv, rv)
        except TypeError:
            raise EvalError(f"values of this type cannot be compared with '{op}'", expr.span)
    raise EvalError(f"internal error: unknown operator '{op}'", expr.span)


def _contains_closure(v):
    if isinstance(v, Closure):
        return True
    if isinstance(v, tuple) or isinstance(v, list):
        return any(_contains_closure(x) for x in v)
    if isinstance(v, SomeV):
        return _contains_closure(v.value)
    return False


def _eval_UnaryNeg(env, expr):
    return -eval_expr(env, expr.expr)


def _eval_Match(env, expr):
    scrutinee = eval_expr(env, expr.scrutinee)
    for pat, body in expr.cases:
        binding = match_pattern(pat, scrutinee)
        if binding is not None:
            env2 = dict(env)
            env2.update(binding)
            return eval_expr(env2, body)
    raise EvalError("non-exhaustive match: no pattern matched the scrutinee value", expr.span)


def match_pattern(pat, value):
    """Return a dict of new bindings if `pat` matches `value`, else None."""
    cls = type(pat).__name__
    if cls == "PWild":
        return {}
    if cls == "PVar":
        return {pat.name: value}
    if cls == "PInt":
        return {} if value == pat.value else None
    if cls == "PBool":
        return {} if value == pat.value else None
    if cls == "PNil":
        return {} if isinstance(value, list) and len(value) == 0 else None
    if cls == "PCons":
        if not isinstance(value, list) or len(value) == 0:
            return None
        h = match_pattern(pat.head, value[0])
        if h is None:
            return None
        t = match_pattern(pat.tail, value[1:])
        if t is None:
            return None
        return {**h, **t}
    if cls == "PTuple":
        if not isinstance(value, tuple) or len(value) != len(pat.items):
            return None
        result = {}
        for p, v in zip(pat.items, value):
            m = match_pattern(p, v)
            if m is None:
                return None
            result.update(m)
        return result
    if cls == "PSome":
        if not isinstance(value, SomeV):
            return None
        return match_pattern(pat.pattern, value.value)
    if cls == "PNone":
        return {} if isinstance(value, NoneV) else None
    raise EvalError(f"internal error: no match rule for pattern {cls}")


_DISPATCH = {
    N.Int: _eval_Int,
    N.Bool: _eval_Bool,
    N.Str: _eval_Str,
    N.Var: _eval_Var,
    N.TupleExpr: _eval_TupleExpr,
    N.Nil: _eval_Nil,
    N.Cons: _eval_Cons,
    N.SomeExpr: _eval_SomeExpr,
    N.NoneExpr: _eval_NoneExpr,
    N.If: _eval_If,
    N.Fun: _eval_Fun,
    N.App: _eval_App,
    N.Let: _eval_Let,
    N.LetRec: _eval_LetRec,
    N.BinOp: _eval_BinOp,
    N.UnaryNeg: _eval_UnaryNeg,
    N.Match: _eval_Match,
}


def format_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, Closure):
        return f"<closure: fun {v.param} -> ...>"
    if isinstance(v, tuple):
        return "(" + ", ".join(format_value(x) for x in v) + ")"
    if isinstance(v, list):
        return "[" + "; ".join(format_value(x) for x in v) + "]"
    if isinstance(v, SomeV):
        return f"Some {format_value(v.value)}"
    if isinstance(v, NoneV):
        return "None"
    return repr(v)
