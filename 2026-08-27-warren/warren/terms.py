"""Prolog term representation shared by the parser, the golden-model
interpreter, and (via reification) the WAM builtins.

Four term kinds, matching the classic Prolog data model:
  Var    - a logic variable (mutable single-assignment cell)
  Atom   - an interned symbolic constant (e.g. `foo`, `[]`, `+`)
  Num    - an integer or float constant
  Struct - a compound term: functor name + tuple of argument terms

Lists are sugar over Struct('.', (Head, Tail)) terminated by Atom('[]'),
exactly like real Prolog.
"""
import itertools

_var_counter = itertools.count()


class Var:
    """An unbound (or bound) logic variable.

    Binding is destructive (``ref`` is set directly) rather than via an
    external substitution map — callers are responsible for trailing any
    variable they bind so it can be unwound on backtracking. This mirrors
    how WAM REF cells work, one representation level up.
    """

    __slots__ = ("name", "ref", "id")

    def __init__(self, name=None):
        self.id = next(_var_counter)
        self.name = name or f"_G{self.id}"
        self.ref = None  # None => unbound

    def __repr__(self):
        return f"Var({self.name}#{self.id})"


_atom_cache = {}


class Atom:
    """An interned atomic constant. Two Atom('foo') are the same object,
    so identity comparison (`is`) doubles as equality."""

    __slots__ = ("name",)

    def __new__(cls, name):
        cached = _atom_cache.get(name)
        if cached is not None:
            return cached
        obj = object.__new__(cls)
        obj.name = name
        _atom_cache[name] = obj
        return obj

    def __repr__(self):
        return f"Atom({self.name!r})"

    def __eq__(self, other):
        return self is other or (isinstance(other, Atom) and other.name == self.name)

    def __hash__(self):
        return hash(("Atom", self.name))


class Num:
    """An integer or float constant."""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Num({self.value!r})"

    def __eq__(self, other):
        return isinstance(other, Num) and self.value == other.value and \
            isinstance(self.value, int) == isinstance(other.value, int)

    def __hash__(self):
        return hash(("Num", self.value))


class Struct:
    """A compound term: functor/arity applied to arguments."""

    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name = name
        self.args = tuple(args)

    @property
    def arity(self):
        return len(self.args)

    @property
    def indicator(self):
        return (self.name, len(self.args))

    def __repr__(self):
        return f"Struct({self.name!r}, {self.args!r})"


NIL = Atom("[]")
TRUE = Atom("true")


def deref(t):
    """Follow a chain of bound Vars to the representative term."""
    while isinstance(t, Var) and t.ref is not None:
        t = t.ref
    return t


def bind(v, t, trail):
    v.ref = t
    trail.append(v)


def undo_to(trail, mark):
    while len(trail) > mark:
        trail.pop().ref = None


def make_list(items, tail=NIL):
    result = tail
    for item in reversed(items):
        result = Struct(".", (item, result))
    return result


def list_to_python(term, allow_partial=False):
    """Deref a Prolog list term into a Python list. Raises ValueError if
    it's not a proper list (unless allow_partial, in which case returns
    (items, tail))."""
    items = []
    t = deref(term)
    while isinstance(t, Struct) and t.name == "." and t.arity == 2:
        items.append(t.args[0])
        t = deref(t.args[1])
    if t is NIL:
        return (items, NIL) if allow_partial else items
    if allow_partial:
        return items, t
    raise ValueError("not a proper list")


def is_indicator(term):
    """True if term looks like a Name/Arity predicate indicator."""
    t = deref(term)
    return (isinstance(t, Struct) and t.name == "/" and t.arity == 2 and
            isinstance(deref(t.args[0]), Atom) and isinstance(deref(t.args[1]), Num))


def copy_term(term, mapping=None):
    """Structurally copy a term, giving fresh Vars to every distinct
    variable encountered (mapping tracks old Var -> new Var)."""
    if mapping is None:
        mapping = {}
    t = deref(term)
    if isinstance(t, Var):
        nv = mapping.get(id(t))
        if nv is None:
            nv = Var(t.name)
            mapping[id(t)] = nv
        return nv
    if isinstance(t, Struct):
        return Struct(t.name, tuple(copy_term(a, mapping) for a in t.args))
    return t  # Atom / Num are immutable constants


def term_vars(term, seen=None, order=None):
    """Return the list of distinct Vars in term, in first-occurrence order."""
    if seen is None:
        seen = set()
        order = []
    t = deref(term)
    if isinstance(t, Var):
        if id(t) not in seen:
            seen.add(id(t))
            order.append(t)
    elif isinstance(t, Struct):
        for a in t.args:
            term_vars(a, seen, order)
    return order
