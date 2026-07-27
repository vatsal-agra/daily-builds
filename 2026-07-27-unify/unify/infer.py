"""Algorithm W: Hindley-Milner type inference with let-polymorphism.

`infer_program(expr)` returns (principal_type, derivation_root) or raises
InferError with the source span of the offending subexpression. The
derivation tree mirrors the typing judgment used at each AST node ("Var",
"App", "Abs", "Let", ...) and is consumed by the CLI's `--trace` flag and
the web visualizer.
"""

from dataclasses import dataclass, field

from . import nodes as N
from .types import (
    TVar, TCon, TFun, TTuple, TList, TOption, Scheme,
    TINT, TBOOL, TSTRING,
    apply, apply_scheme, compose, free_vars, free_vars_scheme, unify_raw,
    UnifyError, pretty,
)


class InferError(Exception):
    def __init__(self, message, span, infinite=False):
        super().__init__(message)
        self.message = message
        self.span = span
        self.infinite = infinite


@dataclass
class Judgment:
    """One node of the type-derivation tree: which rule fired, and its result type."""
    label: str
    expr: object
    ty: object
    children: list = field(default_factory=list)
    note: str = None


COMPARISON_OPS = {"=", "<>", "<", ">", "<=", ">="}
ARITH_OPS = {"+", "-", "*", "/"}
BOOL_OPS = {"&&", "||"}


class Infer:
    def __init__(self):
        self.subst = {}
        self.counter = 0

    def fresh(self):
        self.counter += 1
        return TVar(self.counter)

    def apply(self, ty):
        return apply(self.subst, ty)

    def unify(self, found, expected, span, context=None):
        try:
            s = unify_raw(self.apply(found), self.apply(expected))
        except UnifyError as e:
            prefix = f"{context}: " if context else ""
            raise InferError(f"{prefix}{e.message}", span, infinite=e.infinite) from e
        self.subst = compose(s, self.subst)

    def instantiate(self, scheme):
        if not scheme.vars:
            return scheme.ty
        mapping = {v: self.fresh() for v in scheme.vars}
        return apply(mapping, scheme.ty)

    def generalize(self, env, ty):
        env_free = set()
        for scheme in env.values():
            env_free |= free_vars_scheme(scheme)
        ty_resolved = self.apply(ty)
        quantify = free_vars(ty_resolved) - env_free
        return Scheme(frozenset(quantify), ty_resolved)

    # ---- expressions ----------------------------------------------------

    def infer_expr(self, env, expr):
        method = getattr(self, f"_infer_{type(expr).__name__}", None)
        if method is None:
            raise InferError(f"internal error: no inference rule for {type(expr).__name__}", expr.span)
        return method(env, expr)

    def _infer_Int(self, env, expr):
        return TINT, Judgment("Int", expr, TINT)

    def _infer_Bool(self, env, expr):
        return TBOOL, Judgment("Bool", expr, TBOOL)

    def _infer_Str(self, env, expr):
        return TSTRING, Judgment("Str", expr, TSTRING)

    def _infer_Var(self, env, expr):
        scheme = env.get(expr.name)
        if scheme is None:
            raise InferError(f"unbound variable '{expr.name}'", expr.span)
        ty = self.instantiate(scheme)
        note = f"instantiated from forall {' '.join(pretty(TVar(v)) for v in scheme.vars)}. {pretty(scheme.ty)}" if scheme.vars else None
        return ty, Judgment("Var", expr, ty, note=note)

    def _infer_TupleExpr(self, env, expr):
        types, children = [], []
        for item in expr.items:
            t, j = self.infer_expr(env, item)
            types.append(t)
            children.append(j)
        ty = TTuple(tuple(types))
        return ty, Judgment("Tuple", expr, ty, children)

    def _infer_Nil(self, env, expr):
        ty = TList(self.fresh())
        return ty, Judgment("Nil", expr, ty)

    def _infer_Cons(self, env, expr):
        ht, hj = self.infer_expr(env, expr.head)
        tt, tj = self.infer_expr(env, expr.tail)
        self.unify(tt, TList(ht), expr.tail.span, "list tail must be a list of the head's type")
        ty = self.apply(TList(ht))
        return ty, Judgment("Cons", expr, ty, [hj, tj])

    def _infer_SomeExpr(self, env, expr):
        vt, vj = self.infer_expr(env, expr.value)
        ty = TOption(vt)
        return ty, Judgment("Some", expr, ty, [vj])

    def _infer_NoneExpr(self, env, expr):
        ty = TOption(self.fresh())
        return ty, Judgment("None", expr, ty)

    def _infer_If(self, env, expr):
        ct, cj = self.infer_expr(env, expr.cond)
        self.unify(ct, TBOOL, expr.cond.span, "if condition must be bool")
        tt, tj = self.infer_expr(env, expr.then_branch)
        et, ej = self.infer_expr(env, expr.else_branch)
        self.unify(tt, et, expr.span, "if branches must have the same type")
        ty = self.apply(tt)
        return ty, Judgment("If", expr, ty, [cj, tj, ej])

    def _infer_Fun(self, env, expr):
        pv = self.fresh()
        env2 = dict(env)
        env2[expr.param] = Scheme(frozenset(), pv)
        bt, bj = self.infer_expr(env2, expr.body)
        ty = self.apply(TFun(pv, bt))
        return ty, Judgment("Abs", expr, ty, [bj], note=f"param '{expr.param}'")

    def _infer_App(self, env, expr):
        ft, fj = self.infer_expr(env, expr.fn)
        at, aj = self.infer_expr(env, expr.arg)
        rv = self.fresh()
        self.unify(ft, TFun(at, rv), expr.span, "function application")
        ty = self.apply(rv)
        return ty, Judgment("App", expr, ty, [fj, aj])

    def _infer_Let(self, env, expr):
        vt, vj = self.infer_expr(env, expr.value)
        scheme = self.generalize(env, vt)
        env2 = dict(env)
        env2[expr.name] = scheme
        bt, bj = self.infer_expr(env2, expr.body)
        ty = self.apply(bt)
        return ty, Judgment("Let", expr, ty, [vj, bj], note=f"{expr.name} : {pretty(scheme.ty)}")

    def _infer_LetRec(self, env, expr):
        pv = self.fresh()
        env_rec = dict(env)
        env_rec[expr.name] = Scheme(frozenset(), pv)
        vt, vj = self.infer_expr(env_rec, expr.value)
        self.unify(vt, pv, expr.value.span, f"recursive binding of '{expr.name}'")
        scheme = self.generalize(env, self.apply(pv))
        env2 = dict(env)
        env2[expr.name] = scheme
        bt, bj = self.infer_expr(env2, expr.body)
        ty = self.apply(bt)
        return ty, Judgment("LetRec", expr, ty, [vj, bj], note=f"{expr.name} : {pretty(scheme.ty)}")

    def _infer_BinOp(self, env, expr):
        lt, lj = self.infer_expr(env, expr.left)
        rt, rj = self.infer_expr(env, expr.right)
        op = expr.op
        if op in ARITH_OPS:
            self.unify(lt, TINT, expr.left.span, f"left operand of '{op}'")
            self.unify(rt, TINT, expr.right.span, f"right operand of '{op}'")
            ty = TINT
        elif op in BOOL_OPS:
            self.unify(lt, TBOOL, expr.left.span, f"left operand of '{op}'")
            self.unify(rt, TBOOL, expr.right.span, f"right operand of '{op}'")
            ty = TBOOL
        elif op in COMPARISON_OPS:
            self.unify(lt, rt, expr.span, f"both sides of '{op}' must have the same type")
            ty = TBOOL
        else:
            raise InferError(f"internal error: unknown operator '{op}'", expr.span)
        return ty, Judgment("BinOp", expr, ty, [lj, rj], note=op)

    def _infer_UnaryNeg(self, env, expr):
        et, ej = self.infer_expr(env, expr.expr)
        self.unify(et, TINT, expr.expr.span, "unary '-' operand")
        return TINT, Judgment("Neg", expr, TINT, [ej])

    def _infer_Match(self, env, expr):
        st, sj = self.infer_expr(env, expr.scrutinee)
        result = self.fresh()
        children = [sj]
        for pat, body in expr.cases:
            penv, pt = self.infer_pattern(env, pat)
            self.unify(st, pt, pat.span, "match pattern must match the scrutinee's type")
            bt, bj = self.infer_expr(penv, body)
            self.unify(bt, result, body.span, "all match branches must have the same type")
            children.append(Judgment("Case", body, self.apply(bt), [bj], note=pattern_repr(pat)))
        ty = self.apply(result)
        return ty, Judgment("Match", expr, ty, children)

    # ---- patterns ---------------------------------------------------------

    def infer_pattern(self, env, pat):
        method = getattr(self, f"_pat_{type(pat).__name__}")
        return method(env, pat)

    def _pat_PWild(self, env, pat):
        return env, self.fresh()

    def _pat_PVar(self, env, pat):
        v = self.fresh()
        env2 = dict(env)
        env2[pat.name] = Scheme(frozenset(), v)
        return env2, v

    def _pat_PInt(self, env, pat):
        return env, TINT

    def _pat_PBool(self, env, pat):
        return env, TBOOL

    def _pat_PTuple(self, env, pat):
        cur_env = env
        types = []
        for item in pat.items:
            cur_env, t = self.infer_pattern(cur_env, item)
            types.append(t)
        return cur_env, TTuple(tuple(types))

    def _pat_PNil(self, env, pat):
        return env, TList(self.fresh())

    def _pat_PCons(self, env, pat):
        env1, ht = self.infer_pattern(env, pat.head)
        env2, tt = self.infer_pattern(env1, pat.tail)
        self.unify(tt, TList(ht), pat.span, "list tail pattern must match a list of the head's type")
        return env2, self.apply(TList(ht))

    def _pat_PSome(self, env, pat):
        env1, it = self.infer_pattern(env, pat.pattern)
        return env1, TOption(it)

    def _pat_PNone(self, env, pat):
        return env, TOption(self.fresh())


def pattern_repr(pat):
    cls = type(pat).__name__
    if cls == "PWild":
        return "_"
    if cls == "PVar":
        return pat.name
    if cls == "PInt":
        return str(pat.value)
    if cls == "PBool":
        return "true" if pat.value else "false"
    if cls == "PNil":
        return "[]"
    if cls == "PCons":
        return f"{pattern_repr(pat.head)} :: {pattern_repr(pat.tail)}"
    if cls == "PTuple":
        return "(" + ", ".join(pattern_repr(i) for i in pat.items) + ")"
    if cls == "PSome":
        return f"Some {pattern_repr(pat.pattern)}"
    if cls == "PNone":
        return "None"
    return cls


def _resolve_judgment(j, subst):
    j.ty = apply(subst, j.ty)
    for c in j.children:
        _resolve_judgment(c, subst)
    return j


def infer_program(expr, base_env=None):
    """Infer the principal type of `expr`. Returns (Type, Judgment root).

    Raises InferError on any type error, with a source span to blame.
    """
    inferer = Infer()
    env = dict(base_env) if base_env else {}
    ty, judgment = inferer.infer_expr(env, expr)
    final_ty = inferer.apply(ty)
    _resolve_judgment(judgment, inferer.subst)
    return final_ty, judgment
