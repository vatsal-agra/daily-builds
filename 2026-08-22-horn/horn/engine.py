"""The SLD-resolution engine: clause database, cut, negation-as-failure, and
the top-level solve() generator that drives backtracking search.

solve() is the one recursive, generator-based search procedure in the whole
project. Everything else (unification, the trail, renaming-apart) exists to
support it. There is no "list of remaining choice points" data structure --
backtracking *is* Python generator resumption: asking a suspended generator
for its next value re-enters exactly the point in the search tree where the
last alternative was left, with the trail (not the call stack) recording
what to undo first.
"""

from .errors import HornError
from .terms import Atom, Compound, Var, deref, functor_key, rename
from .unify import unify, undo_to


class CutBarrier:
    """Created once per clause-body activation. A '!' encountered while
    solving that body's goal list sets `.cut = True`; every conjunction
    frame between the cut and the clause-selection loop that owns this
    barrier checks the flag on the way back out and stops offering
    alternatives, which is exactly what "cut commits to this clause and
    everything already decided to its left" means operationally."""

    __slots__ = ("cut",)

    def __init__(self):
        self.cut = False


class Database:
    """Clauses indexed by (functor, arity), in source order."""

    def __init__(self):
        self.clauses = {}

    def add(self, head, body):
        key = functor_key(head)
        if key is None:
            raise HornError(f"type_error: a clause head must be callable, got {head!r}")
        self.clauses.setdefault(key, []).append((head, body))

    def get(self, key):
        return self.clauses.get(key)


class Engine:
    def __init__(self, occurs_check=False, notify=None):
        self.db = Database()
        self.trail = []
        self.occurs_check = occurs_check
        self.builtins = {}
        self.notify = notify or (lambda *a, **k: None)

    def consult_text(self, text, run_directives=True):
        from .parser import parse_program

        for kind, a, b in parse_program(text):
            if kind == "clause":
                self.db.add(a, b)
            else:  # directive
                if run_directives:
                    ok = False
                    for _ in self.solve_top(a):
                        ok = True
                        break
                    if not ok:
                        raise HornError(f"directive failed: {a!r}")

    def solve_top(self, goal):
        """Solve a goal with a fresh top-level cut barrier (a bare '!' in a
        query commits to nothing further up, there being nothing further up)."""
        return solve(goal, self, CutBarrier())


def flatten_conj(term):
    goals = []

    def rec(t):
        if isinstance(t, Compound) and t.functor == "," and t.arity == 2:
            rec(t.args[0])
            rec(t.args[1])
        else:
            goals.append(t)

    rec(term)
    return goals


def solve(term, ctx, barrier):
    """Solve one goal within cut scope `barrier`. A generator: each `next()`
    produces one more solution (bindings live on ctx.trail at yield time)."""
    term = deref(term)
    if isinstance(term, Atom) and term.name == "!":
        yield True
        barrier.cut = True
        return
    if isinstance(term, Compound) and term.functor == "," and term.arity == 2:
        yield from _solve_conj(flatten_conj(term), 0, barrier, ctx)
        return
    if isinstance(term, Compound) and term.functor == "\\+" and term.arity == 1:
        yield from _solve_negation(term.args[0], ctx)
        return
    if isinstance(term, Atom) and term.name in ("true",):
        yield True
        return
    yield from solve_call(term, ctx)


def _solve_conj(goals, idx, barrier, ctx):
    if idx == len(goals):
        yield True
        return
    goal = goals[idx]
    for _ in solve(goal, ctx, barrier):
        yield from _solve_conj(goals, idx + 1, barrier, ctx)
        if barrier.cut:
            return


def _solve_negation(goal, ctx):
    trail = ctx.trail
    mark = len(trail)
    found = False
    for _ in solve(goal, ctx, CutBarrier()):
        found = True
        break
    undo_to(trail, mark)
    if not found:
        yield True


def solve_call(term, ctx):
    if isinstance(term, Atom):
        functor, args = term.name, ()
    elif isinstance(term, Compound):
        functor, args = term.functor, term.args
    elif isinstance(term, Var):
        raise HornError("instantiation_error: an unbound variable cannot be called as a goal")
    else:
        raise HornError(f"type_error: {term!r} is not callable")

    key = (functor, len(args))
    builtin = ctx.builtins.get(key)
    if builtin is not None:
        yield from builtin(args, ctx)
        return

    clauses = ctx.db.get(key)
    if clauses is None:
        raise HornError(f"existence_error: unknown procedure {functor}/{len(args)}")

    trail = ctx.trail
    ctx.notify("call", key)
    for head_t, body_t in list(clauses):
        mark = len(trail)
        mapping = {}
        head2 = rename(head_t, mapping)
        head_args = head2.args if isinstance(head2, Compound) else ()
        ok = True
        for a, b in zip(args, head_args):
            if not unify(a, b, trail, ctx.occurs_check):
                ok = False
                break
        if not ok:
            undo_to(trail, mark)
            continue
        cut_here = False
        if body_t is None:
            ctx.notify("fact", key)
            yield True
        else:
            body2 = rename(body_t, mapping)
            barrier = CutBarrier()
            for _ in solve(body2, ctx, barrier):
                yield True
            cut_here = barrier.cut
        undo_to(trail, mark)
        if cut_here:
            ctx.notify("cut", key)
            return
    ctx.notify("exhausted", key)


def make_engine(occurs_check=False, notify=None, load_stdlib=True):
    """Construct a ready-to-use Engine: builtins installed, and (unless
    disabled) the Horn-native standard library already consulted."""
    import os

    from .builtins import install_builtins

    eng = Engine(occurs_check=occurs_check, notify=notify)
    install_builtins(eng)
    if load_stdlib:
        stdlib_path = os.path.join(os.path.dirname(__file__), "stdlib.horn")
        with open(stdlib_path, encoding="utf-8") as f:
            eng.consult_text(f.read())
    return eng
