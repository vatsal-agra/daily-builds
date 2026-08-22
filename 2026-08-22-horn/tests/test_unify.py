from horn.terms import Atom, Compound, Number, Var, deref
from horn.unify import undo_to, unify


def u(a, b, trail, occurs_check=False):
    return unify(a, b, trail, occurs_check)


def test_atom_unify():
    trail = []
    assert u(Atom("a"), Atom("a"), trail)
    assert not u(Atom("a"), Atom("b"), trail)


def test_number_unify_is_type_sensitive():
    trail = []
    assert u(Number(3), Number(3), trail)
    assert not u(Number(3), Number(3.0), trail)  # int vs float: different terms
    assert u(Number(3.0), Number(3.0), trail)


def test_var_binds_and_derefs():
    trail = []
    x = Var("X")
    assert u(x, Atom("a"), trail)
    assert deref(x) == Atom("a")
    assert trail == [x]


def test_var_var_unify_chains():
    trail = []
    x, y = Var("X"), Var("Y")
    assert u(x, y, trail)
    assert u(y, Atom("a"), trail)
    assert deref(x) == Atom("a")


def test_compound_unify_recurses():
    trail = []
    x = Var("X")
    left = Compound("f", [x, Atom("b")])
    right = Compound("f", [Atom("a"), Atom("b")])
    assert u(left, right, trail)
    assert deref(x) == Atom("a")


def test_compound_arity_mismatch_fails():
    trail = []
    assert not u(Compound("f", [Atom("a")]), Compound("f", [Atom("a"), Atom("b")]), trail)


def test_compound_functor_mismatch_fails():
    trail = []
    assert not u(Compound("f", [Atom("a")]), Compound("g", [Atom("a")]), trail)


def test_occurs_check_rejects_infinite_term():
    trail = []
    x = Var("X")
    term = Compound("f", [x])
    assert u(x, term, trail, occurs_check=True) is False
    trail2 = []
    x2 = Var("X")
    term2 = Compound("f", [x2])
    assert u(x2, term2, trail2, occurs_check=False) is True  # builds a cyclic term


def test_undo_to_restores_prior_state():
    trail = []
    x, y = Var("X"), Var("Y")
    mark = len(trail)
    u(x, Atom("a"), trail)
    u(y, Atom("b"), trail)
    assert deref(x) == Atom("a")
    undo_to(trail, mark)
    assert x.ref is None
    assert y.ref is None
    assert trail == []


def test_partial_undo_only_unwinds_past_mark():
    trail = []
    x, y, z = Var("X"), Var("Y"), Var("Z")
    u(x, Atom("a"), trail)
    mark = len(trail)
    u(y, Atom("b"), trail)
    u(z, Atom("c"), trail)
    undo_to(trail, mark)
    assert deref(x) == Atom("a")  # unaffected: bound before the mark
    assert y.ref is None
    assert z.ref is None
