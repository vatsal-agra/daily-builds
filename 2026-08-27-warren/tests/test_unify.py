from warren.parser import parse_term
from warren.golden import unify
from warren.terms import Var, undo_to, deref, Struct, Atom, Num


def _term(src):
    t, vmap = parse_term(src + ".")
    return t, vmap


def test_basic_unify_binds_var():
    t1, _ = _term("X")
    t2, _ = _term("foo(1,2)")
    trail = []
    assert unify(t1, t2, trail)
    assert deref(t1).name == "foo"


def test_occurs_check_free_unify_would_loop_but_we_dont_check():
    # Warren's unify has no occurs check (matches most Prolog defaults);
    # X = f(X) succeeds, producing a genuinely cyclic term. We just
    # verify it doesn't crash and produces a self-referential binding.
    t1, vmap = _term("X")
    x = vmap["X"]
    t2 = Struct("f", (x,))
    trail = []
    assert unify(t1, t2, trail)
    assert deref(x).args[0] is x


def test_struct_mismatch_fails_and_undoes():
    t1, _ = _term("foo(X,Y)")
    t2, _ = _term("foo(1,2,3)")
    trail = []
    assert not unify(t1, t2, trail)
    assert trail == []


def test_partial_failure_undoes_bindings_made_so_far():
    t1, v1 = _term("foo(X,2)")
    t3, _ = _term("foo(1,3)")
    trail = []
    ok = unify(t1, t3, trail)
    assert not ok  # X would bind to 1, but 2 vs 3 fails
    assert v1["X"].ref is not None  # bound to 1 before the failure was detected
    undo_to(trail, 0)
    assert v1["X"].ref is None


def test_number_type_distinguishes_int_and_float():
    t1, _ = _term("1")
    t2, _ = _term("1.0")
    trail = []
    assert not unify(t1, t2, trail)


def test_atom_identity_after_unify():
    t1, _ = _term("foo")
    t2, _ = _term("foo")
    trail = []
    assert unify(t1, t2, trail)
