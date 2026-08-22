import pytest

from horn.errors import HornError
from horn.parser import parse_program, parse_term
from horn.terms import Atom, Compound, Number, Var, format_term


def test_atom_and_number():
    assert parse_term("foo.") == Atom("foo")
    assert parse_term("42.") == Number(42)
    assert parse_term("3.14.") == Number(3.14)


def test_negative_number_literal_folds_only_when_adjacent():
    t = parse_term("-5.")
    assert isinstance(t, Number) and t.value == -5
    # "- 5" (space between) is the prefix *operator* applied to 5, not a
    # literal -- structurally different, but numerically the same once
    # arithmetic evaluates it (checked in test_engine.py).
    t2 = parse_term("- 5.")
    assert isinstance(t2, Compound) and t2.functor == "-"


def test_compound_term():
    t = parse_term("foo(a, b).")
    assert isinstance(t, Compound)
    assert t.functor == "foo"
    assert t.args == (Atom("a"), Atom("b"))


def test_variable_scope_shares_within_clause_but_not_across():
    t = parse_term("foo(X, X).")
    assert isinstance(t.args[0], Var) and t.args[0] is t.args[1]
    t2 = parse_term("foo(X).")
    assert t2.args[0] is not t.args[0]


def test_anonymous_var_always_fresh():
    t = parse_term("foo(_, _).")
    assert t.args[0] is not t.args[1]


def test_list_syntax():
    t = parse_term("[1, 2, 3].")
    assert format_term(t) == "[1, 2, 3]"
    t2 = parse_term("[].")
    assert format_term(t2) == "[]"
    t3 = parse_term("[H|T].")
    assert isinstance(t3, Compound) and t3.functor == "."


def test_operator_precedence_arithmetic_shape():
    # 1 + 2 * 3 should parse as +(1, *(2,3)), not *(+(1,2), 3)
    t = parse_term("X is 1 + 2 * 3.").args[1]
    assert t.functor == "+"
    assert t.args[1].functor == "*"


def test_rule_and_fact_and_directive():
    items = parse_program("p(1). q(X) :- p(X). :- p(1).")
    kinds = [i[0] for i in items]
    assert kinds == ["clause", "clause", "directive"]
    assert items[1][2] is not None  # q/1 has a body
    assert items[0][2] is None  # p/1 is a fact


def test_comments_are_ignored():
    items = parse_program("% a comment\np(1). /* block\ncomment */ q(2).")
    assert len(items) == 2


def test_cut_is_an_atom():
    t = parse_term("!.")
    assert t == Atom("!")


def test_quoted_atom_with_space():
    t = parse_term("'hello world'.")
    assert t == Atom("hello world")


def test_syntax_error_on_unexpected_token():
    with pytest.raises(HornError):
        parse_term("foo(.")


def test_syntax_error_on_trailing_garbage():
    with pytest.raises(HornError):
        parse_term("foo bar.")


def test_semicolon_is_not_supported_and_errors_cleanly():
    # Deliberate scope decision (see REVIEW.md) -- must fail loudly, not
    # silently parse into something wrong.
    with pytest.raises(HornError):
        parse_term("(a ; b).")
