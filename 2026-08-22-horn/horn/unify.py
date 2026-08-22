"""Unification over first-order terms, with an optional occurs check and a
trail for O(bindings-made) backtracking instead of copying substitutions."""

from .terms import Var, Atom, Number, Compound, deref


def bind(var, value, trail):
    var.ref = value
    trail.append(var)


def undo_to(trail, mark):
    while len(trail) > mark:
        trail.pop().ref = None


def occurs(var, term):
    term = deref(term)
    if term is var:
        return True
    if isinstance(term, Compound):
        return any(occurs(var, a) for a in term.args)
    return False


def unify(t1, t2, trail, occurs_check=False):
    """Unify t1 and t2, extending `trail` with every binding made. On
    failure, bindings made *during this call* are left in place -- the
    caller is responsible for recording a trail mark beforehand and calling
    undo_to() on failure (every call site in this codebase does)."""
    t1 = deref(t1)
    t2 = deref(t2)
    if t1 is t2:
        return True
    if isinstance(t1, Var):
        if occurs_check and occurs(t1, t2):
            return False
        bind(t1, t2, trail)
        return True
    if isinstance(t2, Var):
        if occurs_check and occurs(t2, t1):
            return False
        bind(t2, t1, trail)
        return True
    if isinstance(t1, Atom) and isinstance(t2, Atom):
        return t1.name == t2.name
    if isinstance(t1, Number) and isinstance(t2, Number):
        return t1.value == t2.value and type(t1.value) is type(t2.value)
    if isinstance(t1, Compound) and isinstance(t2, Compound):
        if t1.functor != t2.functor or t1.arity != t2.arity:
            return False
        for a, b in zip(t1.args, t2.args):
            if not unify(a, b, trail, occurs_check):
                return False
        return True
    return False
