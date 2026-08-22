"""Native (Python-implemented) predicates. Everything that *can* be written
as ordinary Horn clauses (append, member, length, ...) lives in stdlib.horn
instead -- this module is only for the primitives that need to reach into
the engine itself: unification, arithmetic, type inspection, I/O, findall,
and halt.
"""

from .arith import eval_arith
from .errors import HaltSignal
from .terms import Atom, Compound, Number, Var, deref, format_term, make_list, rename
from .unify import undo_to, unify


def _unify_det(a, b, ctx):
    """The shared shape for a deterministic builtin that succeeds at most
    once via a single unification: bind, yield, and undo on backtrack (or
    immediately, on failure) so the trail is exactly as if this call had
    never happened once its one solution is exhausted."""
    trail = ctx.trail
    mark = len(trail)
    if unify(a, b, trail, ctx.occurs_check):
        yield True
    undo_to(trail, mark)


def bi_unify(args, ctx):
    yield from _unify_det(args[0], args[1], ctx)


def bi_not_unifiable(args, ctx):
    trail = ctx.trail
    mark = len(trail)
    ok = unify(args[0], args[1], trail, ctx.occurs_check)
    undo_to(trail, mark)
    if not ok:
        yield True


def _struct_eq(a, b):
    a, b = deref(a), deref(b)
    if isinstance(a, Var) or isinstance(b, Var):
        return a is b
    if isinstance(a, Atom) and isinstance(b, Atom):
        return a.name == b.name
    if isinstance(a, Number) and isinstance(b, Number):
        return a.value == b.value and type(a.value) is type(b.value)
    if isinstance(a, Compound) and isinstance(b, Compound):
        return (
            a.functor == b.functor
            and a.arity == b.arity
            and all(_struct_eq(x, y) for x, y in zip(a.args, b.args))
        )
    return False


def bi_struct_eq(args, ctx):
    if _struct_eq(args[0], args[1]):
        yield True


def bi_struct_neq(args, ctx):
    if not _struct_eq(args[0], args[1]):
        yield True


def bi_is(args, ctx):
    value = eval_arith(args[1])
    yield from _unify_det(args[0], Number(value), ctx)


def _cmp(op):
    def fn(args, ctx):
        if op(eval_arith(args[0]), eval_arith(args[1])):
            yield True

    return fn


import operator  # noqa: E402  (grouped near use for readability)

_COMPARISONS = {
    "<": operator.lt,
    ">": operator.gt,
    "=<": operator.le,
    ">=": operator.ge,
    "=:=": operator.eq,
    "=\\=": operator.ne,
}


def bi_var(args, ctx):
    if isinstance(deref(args[0]), Var):
        yield True


def bi_nonvar(args, ctx):
    if not isinstance(deref(args[0]), Var):
        yield True


def bi_atom(args, ctx):
    if isinstance(deref(args[0]), Atom):
        yield True


def bi_number(args, ctx):
    if isinstance(deref(args[0]), Number):
        yield True


def bi_atomic(args, ctx):
    if isinstance(deref(args[0]), (Atom, Number)):
        yield True


def bi_compound(args, ctx):
    if isinstance(deref(args[0]), Compound):
        yield True


def bi_callable(args, ctx):
    if isinstance(deref(args[0]), (Atom, Compound)):
        yield True


def bi_is_list(args, ctx):
    t = deref(args[0])
    while isinstance(t, Compound) and t.functor == "." and t.arity == 2:
        t = deref(t.args[1])
    if isinstance(t, Atom) and t.name == "[]":
        yield True


def bi_true(args, ctx):
    yield True


def bi_fail(args, ctx):
    return
    yield  # pragma: no cover - unreachable; makes this a generator function


def bi_nl(args, ctx):
    print()
    yield True


def bi_write(args, ctx):
    print(format_term(args[0]), end="")
    yield True


def bi_writeln(args, ctx):
    print(format_term(args[0]))
    yield True


def bi_halt0(args, ctx):
    raise HaltSignal(0)
    yield  # pragma: no cover


def bi_halt1(args, ctx):
    code = eval_arith(args[0])
    raise HaltSignal(code)
    yield  # pragma: no cover


def bi_findall(args, ctx):
    from .engine import CutBarrier, solve

    template, goal, result_var = args
    trail = ctx.trail
    mark = len(trail)
    collected = []
    for _ in solve(goal, ctx, CutBarrier()):
        collected.append(rename(template, {}))
    undo_to(trail, mark)
    yield from _unify_det(result_var, make_list(collected), ctx)


BUILTIN_TABLE = {
    ("=", 2): bi_unify,
    ("\\=", 2): bi_not_unifiable,
    ("==", 2): bi_struct_eq,
    ("\\==", 2): bi_struct_neq,
    ("is", 2): bi_is,
    ("var", 1): bi_var,
    ("nonvar", 1): bi_nonvar,
    ("atom", 1): bi_atom,
    ("number", 1): bi_number,
    ("atomic", 1): bi_atomic,
    ("compound", 1): bi_compound,
    ("callable", 1): bi_callable,
    ("is_list", 1): bi_is_list,
    ("true", 0): bi_true,
    ("fail", 0): bi_fail,
    ("false", 0): bi_fail,
    ("nl", 0): bi_nl,
    ("write", 1): bi_write,
    ("writeln", 1): bi_writeln,
    ("halt", 0): bi_halt0,
    ("halt", 1): bi_halt1,
    ("findall", 3): bi_findall,
}
for _name, _op in _COMPARISONS.items():
    BUILTIN_TABLE[(_name, 2)] = _cmp(_op)


def install_builtins(engine):
    engine.builtins.update(BUILTIN_TABLE)
