"""Term representation for Horn: Atom, Number, Var, Compound.

Lists are represented the classic Prolog way: the atom '[]' is nil, and
[H|T] is the compound './2' (functor '.', two args). There is no separate
list type -- unification, renaming, and printing all go through the same
compound machinery a list would need anyway.
"""


class Atom:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, Atom) and self.name == other.name

    def __hash__(self):
        return hash(("Atom", self.name))

    def __repr__(self):
        return self.name


NIL = Atom("[]")


class Number:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return (
            isinstance(other, Number)
            and self.value == other.value
            and type(self.value) is type(other.value)
        )

    def __hash__(self):
        return hash(("Number", self.value))

    def __repr__(self):
        return repr(self.value)


class Var:
    """A logic variable. `ref` is None while unbound, else the term it is
    bound to. Binding/unbinding always goes through unify.bind/undo_to so
    the trail stays the single source of truth for backtracking -- nothing
    else is ever allowed to mutate `ref` directly."""

    __slots__ = ("name", "ref", "id")
    _counter = [0]

    def __init__(self, name="_"):
        self.name = name
        self.ref = None
        Var._counter[0] += 1
        self.id = Var._counter[0]

    def __repr__(self):
        return f"_{self.name}{self.id}" if self.name != "_" else f"_G{self.id}"


class Compound:
    __slots__ = ("functor", "args")

    def __init__(self, functor, args):
        self.functor = functor
        self.args = tuple(args)

    @property
    def arity(self):
        return len(self.args)

    def __repr__(self):
        return f"{self.functor}({', '.join(map(repr, self.args))})"


def deref(t):
    """Follow a chain of bound Vars down to the representative term."""
    while isinstance(t, Var) and t.ref is not None:
        t = t.ref
    return t


def is_nil(t):
    t = deref(t)
    return isinstance(t, Atom) and t.name == "[]"


def is_cons(t):
    t = deref(t)
    return isinstance(t, Compound) and t.functor == "." and t.arity == 2


def make_list(items, tail=None):
    result = tail if tail is not None else NIL
    for item in reversed(items):
        result = Compound(".", [item, result])
    return result


def list_to_python(t, allow_partial=False):
    """Convert a Horn list term to a Python list. Raises ValueError if `t`
    is not a proper (nil-terminated) list, unless allow_partial is set, in
    which case a (items, dangling_tail_or_None) pair is returned."""
    items = []
    t = deref(t)
    while is_cons(t):
        c = deref(t)
        items.append(c.args[0])
        t = deref(c.args[1])
    if is_nil(t):
        return (items, None) if allow_partial else items
    if allow_partial:
        return items, t
    raise ValueError("not a proper list")


def functor_key(t):
    """(name, arity) for an Atom or Compound, else None."""
    t = deref(t)
    if isinstance(t, Atom):
        return (t.name, 0)
    if isinstance(t, Compound):
        return (t.functor, t.arity)
    return None


def rename(term, mapping):
    """Return a structural copy of `term` with every variable replaced by a
    fresh one, consistently per distinct variable (per `mapping`, which the
    caller controls the lifetime of). Bound variables are dereferenced
    first, so this doubles as both:
      - clause "renaming apart" (template vars are always unbound, so
        deref is a no-op -- every clause use gets fresh local variables), and
      - copy_term-style snapshotting of a live, partially-bound term (e.g.
        for findall/3), where bound vars are resolved to their value and
        only genuinely free variables are freshened.
    Atoms and Numbers are immutable and shared as-is.
    """
    term = deref(term)
    if isinstance(term, Var):
        if term not in mapping:
            mapping[term] = Var(term.name)
        return mapping[term]
    if isinstance(term, Compound):
        return Compound(term.functor, [rename(a, mapping) for a in term.args])
    return term


_NEEDS_QUOTE = None


def _atom_needs_quote(name):
    global _NEEDS_QUOTE
    if _NEEDS_QUOTE is None:
        import re

        _NEEDS_QUOTE = re.compile(r"^[a-z][A-Za-z0-9_]*$|^[+\-*/\\^<>=~:.?@#&]+$")
    if name in ("[]", "!", ";", ",", "{}"):
        return False
    return not _NEEDS_QUOTE.match(name)


def format_term(t, depth=0):
    """Render a term the way a Prolog top-level would: lists as [a,b,c],
    quoted atoms only when they'd otherwise be ambiguous to re-read."""
    if depth > 200:
        # Guard against formatting a cyclic term (possible whenever the
        # occurs check is off, e.g. `X = f(X)`) or an absurdly deep
        # non-list one: unlike list nesting (unrolled iteratively below via
        # list_to_python), general compound nesting recurses through a
        # generator expression per level -- roughly 2 Python stack frames
        # per term-depth level, not 1 -- so this needs real margin below
        # Python's own default recursion limit (1000), not just a hair
        # under it. Measured: without this guard, `write(X)` on a cyclic
        # `X = f(X)` term crashes with a raw RecursionError instead of
        # printing anything.
        return "..."
    t = deref(t)
    if isinstance(t, Var):
        return f"_{t.name}" if t.name != "_" else f"_G{t.id}"
    if isinstance(t, Number):
        return str(t.value)
    if isinstance(t, Atom):
        if _atom_needs_quote(t.name):
            escaped = t.name.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"
        return t.name
    if isinstance(t, Compound):
        if t.functor == "." and t.arity == 2:
            items, tail = list_to_python(t, allow_partial=True)
            inner = ", ".join(format_term(i, depth + 1) for i in items)
            if tail is None:
                return f"[{inner}]"
            return f"[{inner}|{format_term(tail, depth + 1)}]"
        args = ", ".join(format_term(a, depth + 1) for a in t.args)
        return f"{t.functor}({args})"
    return str(t)
