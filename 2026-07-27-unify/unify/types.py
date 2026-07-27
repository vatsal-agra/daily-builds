"""Type representations, unification, substitution, and pretty-printing.

This is the mechanical core of Hindley-Milner: types are plain data, a
Substitution is a finite map from type-variable id to Type, and `unify_raw`
computes the most general unifier of two types (or raises UnifyError,
including an occurs check that rejects infinite types).
"""

from dataclasses import dataclass


class Type:
    pass


@dataclass(frozen=True)
class TVar(Type):
    id: int


@dataclass(frozen=True)
class TCon(Type):
    name: str  # "int" | "bool" | "string"


@dataclass(frozen=True)
class TFun(Type):
    arg: Type
    ret: Type


@dataclass(frozen=True)
class TTuple(Type):
    items: tuple  # tuple[Type, ...]


@dataclass(frozen=True)
class TList(Type):
    elem: Type


@dataclass(frozen=True)
class TOption(Type):
    elem: Type


TINT = TCon("int")
TBOOL = TCon("bool")
TSTRING = TCon("string")


@dataclass
class Scheme:
    """A polytype: forall vars. ty  -- the result of generalizing a let-binding."""
    vars: frozenset
    ty: Type


class UnifyError(Exception):
    def __init__(self, message, a, b, infinite=False):
        super().__init__(message)
        self.message = message
        self.a = a
        self.b = b
        self.infinite = infinite


# ---- substitution -----------------------------------------------------

def apply(subst, ty):
    """Apply a substitution (dict: var id -> Type) to `ty`, resolving chains."""
    if isinstance(ty, TVar):
        if ty.id in subst:
            return apply(subst, subst[ty.id])
        return ty
    if isinstance(ty, TFun):
        return TFun(apply(subst, ty.arg), apply(subst, ty.ret))
    if isinstance(ty, TTuple):
        return TTuple(tuple(apply(subst, t) for t in ty.items))
    if isinstance(ty, TList):
        return TList(apply(subst, ty.elem))
    if isinstance(ty, TOption):
        return TOption(apply(subst, ty.elem))
    return ty  # TCon


def apply_scheme(subst, scheme):
    # Quantified vars are bound within the scheme and must not be substituted,
    # even if (due to id reuse across separate inference runs) they collide
    # with a key in `subst`.
    filtered = {k: v for k, v in subst.items() if k not in scheme.vars}
    return Scheme(scheme.vars, apply(filtered, scheme.ty))


def compose(s1, s2):
    """Return a substitution equivalent to applying s2 then s1."""
    result = {k: apply(s1, v) for k, v in s2.items()}
    for k, v in s1.items():
        if k not in result:
            result[k] = v
    return result


def free_vars(ty):
    if isinstance(ty, TVar):
        return {ty.id}
    if isinstance(ty, TFun):
        return free_vars(ty.arg) | free_vars(ty.ret)
    if isinstance(ty, TTuple):
        s = set()
        for t in ty.items:
            s |= free_vars(t)
        return s
    if isinstance(ty, TList) or isinstance(ty, TOption):
        return free_vars(ty.elem)
    return set()


def free_vars_scheme(scheme):
    return free_vars(scheme.ty) - scheme.vars


def occurs(vid, ty):
    if isinstance(ty, TVar):
        return ty.id == vid
    if isinstance(ty, TFun):
        return occurs(vid, ty.arg) or occurs(vid, ty.ret)
    if isinstance(ty, TTuple):
        return any(occurs(vid, t) for t in ty.items)
    if isinstance(ty, TList) or isinstance(ty, TOption):
        return occurs(vid, ty.elem)
    return False


def unify_raw(found, expected):
    """Compute the most general unifier of `found` and `expected`.

    Argument order matters only for error-message wording (which side is
    reported as "expected" vs. "found") — the resulting substitution is the
    same either way. By convention, call sites pass the type an expression
    actually produced as `found`, and the type its context requires as
    `expected`.
    """
    a, b = found, expected
    if isinstance(a, TVar) and isinstance(b, TVar) and a.id == b.id:
        return {}
    if isinstance(a, TVar):
        if occurs(a.id, b):
            raise UnifyError(
                f"infinite type: {pretty(a)} occurs in {pretty(b)}", a, b, infinite=True
            )
        return {a.id: b}
    if isinstance(b, TVar):
        if occurs(b.id, a):
            raise UnifyError(
                f"infinite type: {pretty(b)} occurs in {pretty(a)}", a, b, infinite=True
            )
        return {b.id: a}
    if isinstance(a, TCon) and isinstance(b, TCon):
        if a.name == b.name:
            return {}
        raise UnifyError(f"expected {pretty(b)}, found {pretty(a)}", a, b)
    if isinstance(a, TFun) and isinstance(b, TFun):
        s1 = unify_raw(a.arg, b.arg)
        s2 = unify_raw(apply(s1, a.ret), apply(s1, b.ret))
        return compose(s2, s1)
    if isinstance(a, TTuple) and isinstance(b, TTuple):
        if len(a.items) != len(b.items):
            raise UnifyError(
                f"expected a tuple of {len(b.items)} element(s), "
                f"found one with {len(a.items)}",
                a, b,
            )
        s = {}
        for x, y in zip(a.items, b.items):
            s2 = unify_raw(apply(s, x), apply(s, y))
            s = compose(s2, s)
        return s
    if isinstance(a, TList) and isinstance(b, TList):
        return unify_raw(a.elem, b.elem)
    if isinstance(a, TOption) and isinstance(b, TOption):
        return unify_raw(a.elem, b.elem)
    raise UnifyError(f"expected {pretty(b)}, found {pretty(a)}", a, b)


# ---- pretty-printing ----------------------------------------------------

_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def pretty(ty, var_names=None):
    if var_names is None:
        var_names = {}
        counter = [0]
    else:
        counter = [len(var_names)]

    def name_for(vid):
        if vid not in var_names:
            n = counter[0]
            letter = _LETTERS[n % 26] + (str(n // 26) if n >= 26 else "")
            var_names[vid] = "'" + letter
            counter[0] += 1
        return var_names[vid]

    def go(t, arg_position):
        if isinstance(t, TVar):
            return name_for(t.id)
        if isinstance(t, TCon):
            return t.name
        if isinstance(t, TFun):
            s = f"{go(t.arg, True)} -> {go(t.ret, False)}"
            return f"({s})" if arg_position else s
        if isinstance(t, TTuple):
            return "(" + ", ".join(go(i, False) for i in t.items) + ")"
        if isinstance(t, TList):
            return f"{go(t.elem, True)} list"
        if isinstance(t, TOption):
            return f"{go(t.elem, True)} option"
        raise TypeError(f"unknown type node: {t!r}")

    return go(ty, False)
