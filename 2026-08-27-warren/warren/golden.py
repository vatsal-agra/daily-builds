"""The golden-model interpreter: a deliberately simple, direct
tree-walking SLD-resolution engine. No compilation, no register
machine, no tagged heap — clauses are re-matched against the source
term tree on every call, and Python generators provide backtracking.

This exists to be *obviously correct* by inspection, so it can serve as
an independent oracle the compiled WAM's answers are checked against.
"""
from .terms import Atom, Var, Num, Struct, deref, bind, undo_to, copy_term, make_list, list_to_python
from .errors import PrologError, Cut, type_error, instantiation_error, existence_error
from .arith import eval_arith, compare_arith
from .order import compare_terms, terms_equal
from .pretty import term_to_str

TRUE = Atom("true")
FAIL = Atom("fail")


def unify(a, b, trail):
    a, b = deref(a), deref(b)
    if a is b:
        return True
    if isinstance(a, Var):
        bind(a, b, trail)
        return True
    if isinstance(b, Var):
        bind(b, a, trail)
        return True
    if isinstance(a, Num) and isinstance(b, Num):
        return a.value == b.value and isinstance(a.value, int) == isinstance(b.value, int)
    if isinstance(a, Atom) and isinstance(b, Atom):
        return a.name == b.name
    if isinstance(a, Struct) and isinstance(b, Struct):
        if a.name != b.name or len(a.args) != len(b.args):
            return False
        for x, y in zip(a.args, b.args):
            if not unify(x, y, trail):
                return False
        return True
    return False


def indicator_of(term):
    t = deref(term)
    if isinstance(t, Atom):
        return (t.name, 0)
    if isinstance(t, Struct):
        return (t.name, len(t.args))
    raise type_error("callable", t)


class Database:
    def __init__(self):
        self.preds = {}       # (name,arity) -> list[(head,body)]
        self.dynamic = set()  # predicates declared dynamic (ok if empty/undefined)

    def clauses_for(self, indicator):
        return self.preds.get(indicator)

    def add_clause(self, term, front=False):
        t = deref(term)
        if isinstance(t, Struct) and t.name == ":-" and t.arity == 2:
            head, body = t.args
        else:
            head, body = t, TRUE
        ind = indicator_of(head)
        lst = self.preds.setdefault(ind, [])
        if front:
            lst.insert(0, (head, body))
        else:
            lst.append((head, body))
        return ind

    def declare_dynamic(self, ind):
        self.dynamic.add(ind)
        self.preds.setdefault(ind, [])


class Interpreter:
    """Owns a Database and a `solve` generator implementing SLD
    resolution with cut, if-then-else, negation-as-failure, and a
    library of built-in predicates."""

    def __init__(self, db=None, out=None):
        self.db = db if db is not None else Database()
        self.out = out
        self.builtins = {}
        _register_builtins(self)

    def write(self, s):
        if self.out is not None:
            self.out.write(s)

    # ---- main resolution loop -----------------------------------
    def solve(self, goal, trail, depth):
        g = deref(goal)

        if isinstance(g, Var):
            raise instantiation_error()

        if isinstance(g, Atom):
            name, arity, args = g.name, 0, ()
        elif isinstance(g, Struct):
            name, arity, args = g.name, len(g.args), g.args
        else:
            raise type_error("callable", g)

        # --- control constructs (handled inline, not via the builtin table) ---
        if name == "," and arity == 2:
            A, B = args
            for _ in self.solve(A, trail, depth):
                yield from self.solve(B, trail, depth)
            return

        if name == ";" and arity == 2:
            left = deref(args[0])
            if isinstance(left, Struct) and left.name == "->" and left.arity == 2:
                cond, then = left.args
                els = args[1]
                mark = len(trail)
                found = False
                barrier = object()
                try:
                    for _ in self.solve(cond, trail, barrier):
                        found = True
                        break
                except Cut as c:
                    if c.barrier is not barrier:
                        raise
                    found = True
                if found:
                    yield from self.solve(then, trail, depth)
                else:
                    undo_to(trail, mark)
                    yield from self.solve(els, trail, depth)
                return
            if isinstance(left, Struct) and left.name == "*->" and left.arity == 2:
                cond, then = left.args
                els = args[1]
                mark = len(trail)
                any_sol = False
                for _ in self.solve(cond, trail, depth):
                    any_sol = True
                    yield from self.solve(then, trail, depth)
                if not any_sol:
                    undo_to(trail, mark)
                    yield from self.solve(els, trail, depth)
                return
            mark = len(trail)
            yield from self.solve(args[0], trail, depth)
            undo_to(trail, mark)
            yield from self.solve(args[1], trail, depth)
            return

        if name == "->" and arity == 2:
            cond, then = args
            barrier = object()
            found = False
            try:
                for _ in self.solve(cond, trail, barrier):
                    found = True
                    break
            except Cut as c:
                if c.barrier is not barrier:
                    raise
                found = True
            if found:
                yield from self.solve(then, trail, depth)
            return

        if name == "!" and arity == 0:
            yield
            raise Cut(depth)

        if (name == "true" and arity == 0):
            yield
            return
        if (name in ("fail", "false")) and arity == 0:
            return

        if name == "\\+" and arity == 1:
            mark = len(trail)
            barrier = object()
            succeeded = False
            try:
                for _ in self.solve(args[0], trail, barrier):
                    succeeded = True
                    break
            except Cut as c:
                if c.barrier is not barrier:
                    raise
                succeeded = True
            undo_to(trail, mark)
            if not succeeded:
                yield
            return

        if name == "not" and arity == 1:
            yield from self.solve(Struct("\\+", args), trail, depth)
            return

        if name == "call":
            target = deref(args[0])
            extra = args[1:]
            if extra:
                if isinstance(target, Atom):
                    target = Struct(target.name, extra)
                elif isinstance(target, Struct):
                    target = Struct(target.name, target.args + extra)
                else:
                    raise type_error("callable", target)
            barrier = object()
            try:
                yield from self.solve(target, trail, barrier)
            except Cut as c:
                if c.barrier is not barrier:
                    raise
            return

        if name == "catch" and arity == 3:
            goal_t, catcher, recovery = args
            mark = len(trail)
            barrier = object()
            try:
                try:
                    yield from self.solve(goal_t, trail, barrier)
                except Cut as c:
                    if c.barrier is not barrier:
                        raise
            except PrologError as e:
                undo_to(trail, mark)
                ball = copy_term(e.term)
                if unify(catcher, ball, trail):
                    yield from self.solve(recovery, trail, depth)
                else:
                    raise
            return

        if name == "throw" and arity == 1:
            raise PrologError(copy_term(args[0]))

        # --- built-in predicates ---
        biv = self.builtins.get((name, arity))
        if biv is not None:
            yield from biv(self, args, trail)
            return

        # --- user-defined predicates ---
        ind = (name, arity)
        clauses = self.db.clauses_for(ind)
        if clauses is None:
            if ind in self.db.dynamic:
                return
            raise existence_error("procedure", Struct("/", (Atom(name), Num(arity))))

        my_barrier = object()
        try:
            for head, body in list(clauses):
                mark = len(trail)
                mapping = {}
                h2 = copy_term(head, mapping)
                if unify(g, h2, trail):
                    b2 = copy_term(body, mapping)
                    yield from self.solve(b2, trail, my_barrier)
                undo_to(trail, mark)
        except Cut as c:
            if c.barrier is not my_barrier:
                raise
            return

    def solve_once(self, goal, trail):
        """Run goal for (at most) one solution; return True/False.
        Bindings from a successful call are left on the trail."""
        barrier = object()
        try:
            for _ in self.solve(goal, trail, barrier):
                return True
        except Cut as c:
            if c.barrier is not barrier:
                raise
        return False

    def query(self, goal):
        """Top-level convenience: yield a dict of {name: Term} for each
        solution's query variables, in source order.

        Each yielded term is `copy_term`d -- a fully independent
        snapshot, not a live reference into the mutable binding graph --
        since backtracking (which happens as soon as the caller asks
        for the next solution, or when this generator is exhausted at
        the very end) destructively unbinds Vars in place. Without the
        copy, a caller that collects solutions eagerly (`list(...)`)
        would see every remaining unbound variable in an already-yielded
        answer revert to unbound underneath it.
        """
        from .terms import term_vars
        qvars = [v for v in term_vars(goal) if not v.name.startswith("_")]
        trail = []
        try:
            for _ in self.solve(goal, trail, object()):
                yield {v.name: copy_term(deref(v)) for v in qvars}
        except Cut:
            pass
        undo_to(trail, 0)

    def consult_terms(self, terms):
        from .dcg import translate_dcg
        for t in terms:
            t = deref(t)
            if isinstance(t, Struct) and t.name == ":-" and t.arity == 1:
                directive = t.args[0]
                self._run_directive(directive)
                continue
            if isinstance(t, Struct) and t.name == "-->" and t.arity == 2:
                t = translate_dcg(t)
            self.db.add_clause(t)

    def _run_directive(self, directive):
        d = deref(directive)
        if isinstance(d, Struct) and d.name == "dynamic":
            for ind in _parse_dynamic_spec(d.args[0]):
                self.db.declare_dynamic(ind)
            return
        trail = []
        ok = self.solve_once(d, trail)
        if not ok:
            import sys
            print(f"Warning: directive failed: {term_to_str(d)}", file=sys.stderr)
        undo_to(trail, 0)


def _parse_dynamic_spec(term):
    t = deref(term)
    out = []
    if isinstance(t, Struct) and t.name == "," and t.arity == 2:
        out += _parse_dynamic_spec(t.args[0])
        out += _parse_dynamic_spec(t.args[1])
    elif isinstance(t, Struct) and t.name == "/" and t.arity == 2:
        out.append((deref(t.args[0]).name, deref(t.args[1]).value))
    return out


# ------------------------------------------------------------------
# Built-in predicate library
# ------------------------------------------------------------------
BUILTIN_TABLE = {}


def builtin(name, arity):
    def deco(fn):
        BUILTIN_TABLE[(name, arity)] = fn
        return fn
    return deco


def _register_builtins(interp):
    interp.builtins.update(BUILTIN_TABLE)


def det(cond):
    if cond:
        yield


@builtin("=", 2)
def _bi_unify(interp, args, trail):
    mark = len(trail)
    if unify(args[0], args[1], trail):
        yield
    else:
        undo_to(trail, mark)


@builtin("\\=", 2)
def _bi_nunify(interp, args, trail):
    mark = len(trail)
    ok = unify(args[0], args[1], trail)
    undo_to(trail, mark)
    if not ok:
        yield


@builtin("==", 2)
def _bi_eq(interp, args, trail):
    yield from det(terms_equal(args[0], args[1]))


@builtin("\\==", 2)
def _bi_neq(interp, args, trail):
    yield from det(not terms_equal(args[0], args[1]))


for _op in ("@<", "@>", "@=<", "@>="):
    def _mk(op):
        def f(interp, args, trail):
            c = compare_terms(args[0], args[1])
            ok = {"@<": c < 0, "@>": c > 0, "@=<": c <= 0, "@>=": c >= 0}[op]
            yield from det(ok)
        return f
    BUILTIN_TABLE[(_op, 2)] = _mk(_op)


@builtin("compare", 3)
def _bi_compare(interp, args, trail):
    c = compare_terms(args[1], args[2])
    sym = Atom("<" if c < 0 else (">" if c > 0 else "="))
    if unify(args[0], sym, trail):
        yield


@builtin("is", 2)
def _bi_is(interp, args, trail):
    v = eval_arith(args[1])
    if unify(args[0], Num(v), trail):
        yield


for _op in ("<", ">", "=<", ">=", "=:=", "=\\="):
    def _mkc(op):
        def f(interp, args, trail):
            yield from det(compare_arith(op, args[0], args[1]))
        return f
    BUILTIN_TABLE[(_op, 2)] = _mkc(_op)


@builtin("var", 1)
def _bi_var(interp, args, trail):
    yield from det(isinstance(deref(args[0]), Var))


@builtin("nonvar", 1)
def _bi_nonvar(interp, args, trail):
    yield from det(not isinstance(deref(args[0]), Var))


@builtin("atom", 1)
def _bi_atom(interp, args, trail):
    yield from det(isinstance(deref(args[0]), Atom))


@builtin("number", 1)
def _bi_number(interp, args, trail):
    yield from det(isinstance(deref(args[0]), Num))


@builtin("integer", 1)
def _bi_integer(interp, args, trail):
    t = deref(args[0])
    yield from det(isinstance(t, Num) and isinstance(t.value, int))


@builtin("float", 1)
def _bi_float(interp, args, trail):
    t = deref(args[0])
    yield from det(isinstance(t, Num) and isinstance(t.value, float))


@builtin("atomic", 1)
def _bi_atomic(interp, args, trail):
    yield from det(isinstance(deref(args[0]), (Atom, Num)))


@builtin("compound", 1)
def _bi_compound(interp, args, trail):
    yield from det(isinstance(deref(args[0]), Struct))


@builtin("callable", 1)
def _bi_callable(interp, args, trail):
    yield from det(isinstance(deref(args[0]), (Atom, Struct)))


@builtin("is_list", 1)
def _bi_islist(interp, args, trail):
    t = deref(args[0])
    while isinstance(t, Struct) and t.name == "." and t.arity == 2:
        t = deref(t.args[1])
    yield from det(isinstance(t, Atom) and t.name == "[]")


@builtin("ground", 1)
def _bi_ground(interp, args, trail):
    from .terms import term_vars
    yield from det(len(term_vars(args[0])) == 0)


@builtin("functor", 3)
def _bi_functor(interp, args, trail):
    t = deref(args[0])
    if isinstance(t, Var):
        name_t, ar_t = deref(args[1]), deref(args[2])
        if isinstance(ar_t, Var) or isinstance(name_t, Var):
            raise instantiation_error()
        ar = ar_t.value
        if ar == 0:
            if unify(t, name_t, trail):
                yield
            return
        nm = name_t.name
        newt = Struct(nm, tuple(Var() for _ in range(ar)))
        if unify(t, newt, trail):
            yield
        return
    if isinstance(t, Struct):
        if unify(args[1], Atom(t.name), trail) and unify(args[2], Num(len(t.args)), trail):
            yield
    else:
        nm = Atom(t.name) if isinstance(t, Atom) else t
        if unify(args[1], nm, trail) and unify(args[2], Num(0), trail):
            yield


@builtin("arg", 3)
def _bi_arg(interp, args, trail):
    n = deref(args[0])
    t = deref(args[1])
    if not isinstance(t, Struct):
        raise type_error("compound", t)
    if isinstance(n, Var):
        for i, a in enumerate(t.args, start=1):
            mark = len(trail)
            if unify(n, Num(i), trail) and unify(args[2], a, trail):
                yield
            undo_to(trail, mark)
        return
    i = n.value
    if 1 <= i <= len(t.args):
        if unify(args[2], t.args[i - 1], trail):
            yield


@builtin("=..", 2)
def _bi_univ(interp, args, trail):
    t = deref(args[0])
    if isinstance(t, Var):
        items = list_to_python(args[1])
        if len(items) == 1:
            if unify(t, items[0], trail):
                yield
            return
        head = deref(items[0])
        newt = Struct(head.name, tuple(items[1:]))
        if unify(t, newt, trail):
            yield
        return
    if isinstance(t, Struct):
        lst = make_list([Atom(t.name)] + list(t.args))
    elif isinstance(t, Atom):
        lst = make_list([t])
    else:
        lst = make_list([t])
    if unify(args[1], lst, trail):
        yield


@builtin("copy_term", 2)
def _bi_copy_term(interp, args, trail):
    c = copy_term(args[0])
    if unify(args[1], c, trail):
        yield


@builtin("findall", 3)
def _bi_findall(interp, args, trail):
    template, goal, result = args
    results = []
    inner_trail = []
    barrier = object()
    try:
        for _ in interp.solve(goal, inner_trail, barrier):
            results.append(copy_term(template))
    except Cut as c:
        if c.barrier is not barrier:
            raise
    undo_to(inner_trail, 0)
    if unify(result, make_list(results), trail):
        yield


@builtin("forall", 2)
def _bi_forall(interp, args, trail):
    cond, action = args
    inner_trail = []
    barrier = object()
    ok = True
    try:
        for _ in interp.solve(cond, inner_trail, barrier):
            if not interp.solve_once(action, inner_trail):
                ok = False
                break
    except Cut as c:
        if c.barrier is not barrier:
            raise
    undo_to(inner_trail, 0)
    yield from det(ok)


@builtin("aggregate_all", 3)
def _bi_aggregate_all(interp, args, trail):
    spec, goal, result = args
    spec_t = deref(spec)
    if isinstance(spec_t, Struct) and spec_t.arity == 1 and spec_t.name in ("count", "bag", "set", "sum", "max", "min"):
        template = spec_t.args[0]
    else:
        template = spec_t
    results = []
    inner_trail = []
    barrier = object()
    try:
        for _ in interp.solve(goal, inner_trail, barrier):
            results.append(copy_term(template))
    except Cut as c:
        if c.barrier is not barrier:
            raise
    undo_to(inner_trail, 0)
    kind = spec_t.name if isinstance(spec_t, Struct) else "bag"
    if kind == "count":
        out = Num(len(results))
    elif kind == "sum":
        out = Num(sum(eval_arith(r) for r in results) if results else 0)
    elif kind == "max":
        out = Num(max(eval_arith(r) for r in results))
    elif kind == "min":
        out = Num(min(eval_arith(r) for r in results))
    elif kind == "set":
        import functools
        uniq = []
        for r in sorted(results, key=functools.cmp_to_key(compare_terms)):
            if not uniq or not terms_equal(uniq[-1], r):
                uniq.append(r)
        out = make_list(uniq)
    else:
        out = make_list(results)
    if unify(result, out, trail):
        yield


@builtin("bagof", 3)
def _bi_bagof(interp, args, trail):
    template, goal, result = args
    g = deref(goal)
    while isinstance(g, Struct) and g.name == "^" and g.arity == 2:
        g = deref(g.args[1])
    results = []
    inner_trail = []
    barrier = object()
    try:
        for _ in interp.solve(g, inner_trail, barrier):
            results.append(copy_term(template))
    except Cut as c:
        if c.barrier is not barrier:
            raise
    undo_to(inner_trail, 0)
    if results and unify(result, make_list(results), trail):
        yield


@builtin("setof", 3)
def _bi_setof(interp, args, trail):
    template, goal, result = args
    g = deref(goal)
    while isinstance(g, Struct) and g.name == "^" and g.arity == 2:
        g = deref(g.args[1])
    results = []
    inner_trail = []
    barrier = object()
    try:
        for _ in interp.solve(g, inner_trail, barrier):
            results.append(copy_term(template))
    except Cut as c:
        if c.barrier is not barrier:
            raise
    undo_to(inner_trail, 0)
    if not results:
        return
    import functools
    results.sort(key=functools.cmp_to_key(compare_terms))
    uniq = [results[0]]
    for r in results[1:]:
        if not terms_equal(uniq[-1], r):
            uniq.append(r)
    if unify(result, make_list(uniq), trail):
        yield


@builtin("between", 3)
def _bi_between(interp, args, trail):
    lo = eval_arith(args[0])
    hi_t = deref(args[1])
    hi = eval_arith(args[1]) if not (isinstance(hi_t, Atom) and hi_t.name in ("inf", "infinite")) else None
    x = deref(args[2])
    if isinstance(x, Num):
        if lo <= x.value and (hi is None or x.value <= hi):
            yield
        return
    v = lo
    while hi is None or v <= hi:
        mark = len(trail)
        if unify(args[2], Num(v), trail):
            yield
        undo_to(trail, mark)
        v += 1


@builtin("succ", 2)
def _bi_succ(interp, args, trail):
    a, b = deref(args[0]), deref(args[1])
    if isinstance(a, Num):
        if unify(b, Num(a.value + 1), trail):
            yield
    elif isinstance(b, Num):
        if b.value > 0 and unify(a, Num(b.value - 1), trail):
            yield
    else:
        raise instantiation_error()


@builtin("plus", 3)
def _bi_plus(interp, args, trail):
    a, b, c = deref(args[0]), deref(args[1]), deref(args[2])
    if isinstance(a, Num) and isinstance(b, Num):
        if unify(c, Num(a.value + b.value), trail):
            yield
    elif isinstance(a, Num) and isinstance(c, Num):
        if unify(b, Num(c.value - a.value), trail):
            yield
    elif isinstance(b, Num) and isinstance(c, Num):
        if unify(a, Num(c.value - b.value), trail):
            yield
    else:
        raise instantiation_error()


def _text_of(t):
    t = deref(t)
    if isinstance(t, Atom):
        return t.name
    if isinstance(t, Num):
        return term_to_str(t)
    raise type_error("atomic", t)


@builtin("atom_codes", 2)
def _bi_atom_codes(interp, args, trail):
    t = deref(args[0])
    if not isinstance(t, Var):
        s = _text_of(t)
        if unify(args[1], make_list([Num(ord(c)) for c in s]), trail):
            yield
        return
    codes = list_to_python(args[1])
    s = "".join(chr(deref(c).value) for c in codes)
    if unify(t, Atom(s), trail):
        yield


@builtin("atom_chars", 2)
def _bi_atom_chars(interp, args, trail):
    t = deref(args[0])
    if not isinstance(t, Var):
        s = _text_of(t)
        if unify(args[1], make_list([Atom(c) for c in s]), trail):
            yield
        return
    chars = list_to_python(args[1])
    s = "".join(deref(c).name for c in chars)
    if unify(t, Atom(s), trail):
        yield


@builtin("char_code", 2)
def _bi_char_code(interp, args, trail):
    a = deref(args[0])
    if isinstance(a, Atom):
        if unify(args[1], Num(ord(a.name)), trail):
            yield
        return
    b = deref(args[1])
    if unify(args[0], Atom(chr(b.value)), trail):
        yield


@builtin("number_codes", 2)
def _bi_number_codes(interp, args, trail):
    t = deref(args[0])
    if isinstance(t, Num):
        s = term_to_str(t)
        if unify(args[1], make_list([Num(ord(c)) for c in s]), trail):
            yield
        return
    codes = list_to_python(args[1])
    s = "".join(chr(deref(c).value) for c in codes)
    try:
        v = int(s)
    except ValueError:
        v = float(s)
    if unify(t, Num(v), trail):
        yield


@builtin("number_chars", 2)
def _bi_number_chars(interp, args, trail):
    t = deref(args[0])
    if isinstance(t, Num):
        s = term_to_str(t)
        if unify(args[1], make_list([Atom(c) for c in s]), trail):
            yield
        return
    chars = list_to_python(args[1])
    s = "".join(deref(c).name for c in chars)
    try:
        v = int(s)
    except ValueError:
        v = float(s)
    if unify(t, Num(v), trail):
        yield


@builtin("atom_length", 2)
def _bi_atom_length(interp, args, trail):
    s = _text_of(args[0])
    if unify(args[1], Num(len(s)), trail):
        yield


@builtin("upcase_atom", 2)
def _bi_upcase(interp, args, trail):
    if unify(args[1], Atom(_text_of(args[0]).upper()), trail):
        yield


@builtin("downcase_atom", 2)
def _bi_downcase(interp, args, trail):
    if unify(args[1], Atom(_text_of(args[0]).lower()), trail):
        yield


@builtin("atom_concat", 3)
def _bi_atom_concat(interp, args, trail):
    a, b, c = deref(args[0]), deref(args[1]), deref(args[2])
    if not isinstance(a, Var) and not isinstance(b, Var):
        if unify(c, Atom(_text_of(a) + _text_of(b)), trail):
            yield
        return
    s = _text_of(c)
    for i in range(len(s) + 1):
        mark = len(trail)
        if unify(a, Atom(s[:i]), trail) and unify(b, Atom(s[i:]), trail):
            yield
        undo_to(trail, mark)


@builtin("split_string", 4)
def _bi_split_string(interp, args, trail):
    s = _text_of(args[0])
    seps = _text_of(args[1])
    pad = _text_of(args[2])
    if seps == "":
        parts = [s]
    else:
        parts = []
        cur = []
        for ch in s:
            if ch in seps:
                parts.append("".join(cur))
                cur = []
            else:
                cur.append(ch)
        parts.append("".join(cur))
    parts = [p.strip(pad) if pad else p for p in parts]
    if unify(args[3], make_list([Atom(p) for p in parts]), trail):
        yield


@builtin("string_concat", 3)
def _bi_string_concat(interp, args, trail):
    yield from _bi_atom_concat(interp, args, trail)


@builtin("string_chars", 2)
def _bi_string_chars(interp, args, trail):
    yield from _bi_atom_chars(interp, args, trail)


@builtin("string_to_atom", 2)
def _bi_string_to_atom(interp, args, trail):
    a, b = deref(args[0]), deref(args[1])
    if not isinstance(a, Var):
        if unify(b, Atom(_text_of(a)), trail):
            yield
    else:
        if unify(a, Atom(_text_of(b)), trail):
            yield


@builtin("term_to_atom", 2)
def _bi_term_to_atom(interp, args, trail):
    t = deref(args[0])
    if unify(args[1], Atom(term_to_str(t, quoted=True)), trail):
        yield


@builtin("sort", 2)
def _bi_sort(interp, args, trail):
    import functools
    items = list_to_python(args[0])
    items = sorted(items, key=functools.cmp_to_key(compare_terms))
    uniq = []
    for it in items:
        if not uniq or not terms_equal(uniq[-1], it):
            uniq.append(it)
    if unify(args[1], make_list(uniq), trail):
        yield


@builtin("msort", 2)
def _bi_msort(interp, args, trail):
    import functools
    items = list_to_python(args[0])
    items = sorted(items, key=functools.cmp_to_key(compare_terms))
    if unify(args[1], make_list(items), trail):
        yield


@builtin("keysort", 2)
def _bi_keysort(interp, args, trail):
    import functools
    items = list_to_python(args[0])

    def key_of(pair):
        p = deref(pair)
        return p.args[0]
    items = sorted(items, key=functools.cmp_to_key(lambda a, b: compare_terms(key_of(a), key_of(b))))
    if unify(args[1], make_list(items), trail):
        yield


@builtin("length", 2)
def _bi_length(interp, args, trail):
    lst, n = deref(args[0]), deref(args[1])
    items, tail = list_to_python(lst, allow_partial=True)
    if isinstance(tail, Atom) and tail.name == "[]":
        if unify(n, Num(len(items)), trail):
            yield
        return
    if isinstance(tail, Var):
        if isinstance(n, Num):
            need = n.value - len(items)
            if need < 0:
                return
            newvars = [Var() for _ in range(need)]
            if unify(tail, make_list(newvars), trail):
                yield
            return
        k = len(items)
        while True:
            mark = len(trail)
            newvars = [Var() for _ in range(k - len(items))]
            if unify(tail, make_list(newvars), trail) and unify(n, Num(k), trail):
                yield
            undo_to(trail, mark)
            k += 1
            if k > len(items) + 10000:
                return


@builtin("assert", 1)
@builtin("assertz", 1)
def _bi_assertz(interp, args, trail):
    ind = interp.db.add_clause(copy_term(args[0]))
    interp.db.dynamic.add(ind)
    yield


@builtin("asserta", 1)
def _bi_asserta(interp, args, trail):
    ind = interp.db.add_clause(copy_term(args[0]), front=True)
    interp.db.dynamic.add(ind)
    yield


@builtin("retract", 1)
def _bi_retract(interp, args, trail):
    t = deref(args[0])
    if isinstance(t, Struct) and t.name == ":-" and t.arity == 2:
        pat_head, pat_body = t.args
    else:
        pat_head, pat_body = t, TRUE
    ind = indicator_of(pat_head)
    clauses = interp.db.preds.get(ind, [])
    for i, (h, b) in enumerate(clauses):
        mark = len(trail)
        mapping = {}
        h2, b2 = copy_term(h, mapping), copy_term(b, mapping)
        if unify(pat_head, h2, trail) and unify(pat_body, b2, trail):
            del clauses[i]
            yield
            return
        undo_to(trail, mark)


@builtin("retractall", 1)
def _bi_retractall(interp, args, trail):
    pat_head = deref(args[0])
    ind = indicator_of(pat_head)
    clauses = interp.db.preds.get(ind, [])
    kept = []
    for h, b in clauses:
        mark = len(trail)
        if not unify(pat_head, copy_term(h), trail):
            kept.append((h, b))
        undo_to(trail, mark)
    interp.db.preds[ind] = kept
    interp.db.dynamic.add(ind)
    yield


@builtin("clause", 2)
def _bi_clause(interp, args, trail):
    head = deref(args[0])
    ind = indicator_of(head)
    for h, b in list(interp.db.preds.get(ind, [])):
        mark = len(trail)
        mapping = {}
        h2, b2 = copy_term(h, mapping), copy_term(b, mapping)
        if unify(head, h2, trail) and unify(args[1], b2, trail):
            yield
        undo_to(trail, mark)


@builtin("write", 1)
def _bi_write(interp, args, trail):
    interp.write(term_to_str(args[0]))
    yield


@builtin("print", 1)
def _bi_print(interp, args, trail):
    interp.write(term_to_str(args[0], quoted=True))
    yield


@builtin("writeln", 1)
def _bi_writeln(interp, args, trail):
    interp.write(term_to_str(args[0]) + "\n")
    yield


@builtin("write_canonical", 1)
@builtin("writeq", 1)
def _bi_writeq(interp, args, trail):
    interp.write(term_to_str(args[0], quoted=True))
    yield


@builtin("nl", 0)
def _bi_nl(interp, args, trail):
    interp.write("\n")
    yield


@builtin("tab", 1)
def _bi_tab(interp, args, trail):
    interp.write(" " * int(eval_arith(args[0])))
    yield


@builtin("halt", 0)
def _bi_halt0(interp, args, trail):
    raise SystemExit(0)


@builtin("halt", 1)
def _bi_halt1(interp, args, trail):
    raise SystemExit(int(eval_arith(args[0])))
