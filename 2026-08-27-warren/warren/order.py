"""Standard order of terms: Var @< Num @< Atom @< Struct, used by ==, @<,
compare/3, sort/2, msort/2, and setof/bagof key ordering."""
from .terms import Var, Num, Atom, Struct, deref


def _rank(t):
    if isinstance(t, Var):
        return 0
    if isinstance(t, Num):
        return 1
    if isinstance(t, Atom):
        return 2
    return 3


def compare_terms(a, b):
    a, b = deref(a), deref(b)
    ra, rb = _rank(a), _rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if ra == 0:
        return -1 if a.id < b.id else (1 if a.id > b.id else 0)
    if ra == 1:
        if a.value == b.value:
            return 0
        return -1 if a.value < b.value else 1
    if ra == 2:
        if a.name == b.name:
            return 0
        return -1 if a.name < b.name else 1
    if len(a.args) != len(b.args):
        return -1 if len(a.args) < len(b.args) else 1
    if a.name != b.name:
        return -1 if a.name < b.name else 1
    for x, y in zip(a.args, b.args):
        c = compare_terms(x, y)
        if c != 0:
            return c
    return 0


def terms_equal(a, b):
    return compare_terms(a, b) == 0
