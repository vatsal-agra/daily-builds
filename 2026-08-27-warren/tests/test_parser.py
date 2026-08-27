from warren.parser import parse_program, parse_term
from warren.terms import Struct, Atom, Var, Num, deref
from warren.pretty import term_to_str


def _one(src):
    return parse_program(src)[0]


def test_atom_and_number():
    assert _one("foo.") == Atom("foo")
    t = _one("42.")
    assert isinstance(t, Num) and t.value == 42


def test_operator_precedence():
    t = _one("a + b * c = X.")
    assert isinstance(t, Struct) and t.name == "="
    rhs = t.args[0]
    assert rhs.name == "+"
    assert rhs.args[1].name == "*"


def test_right_associative_arrow_and_comma():
    t = _one("a :- b, c, d.")
    assert t.name == ":-"
    body = t.args[1]
    assert body.name == "," and body.args[0] == Atom("b")
    assert body.args[1].name == "," and body.args[1].args[0] == Atom("c")


def test_list_sugar():
    t = _one("[1,2,3|T].")
    assert t.name == "." and t.args[0].value == 1
    assert t.args[1].name == "."


def test_negative_number_literal_vs_prefix_minus():
    t = _one("X = -1.")
    assert isinstance(t.args[1], Num) and t.args[1].value == -1
    t2 = _one("X is - 1.")
    # "- 1" (with a space) parses as prefix '-' applied to 1, not a literal
    assert t2.args[1].name == "-"


def test_shared_variables_within_one_clause():
    t = _one("p(X, X).")
    assert t.args[0] is t.args[1]


def test_variables_do_not_leak_across_clauses():
    terms = parse_program("p(X). q(X).")
    v1 = terms[0].args[0]
    v2 = terms[1].args[0]
    assert v1 is not v2


def test_quoted_atom_roundtrip():
    t = _one("'hello world'(a).")
    assert t.name == "hello world"
    assert "'hello world'" in term_to_str(t, quoted=True)


def test_dcg_arrow_parses():
    t = _one("greeting --> [hello], [world].")
    assert t.name == "-->"


def test_curly_braces():
    t = _one("a :- { X is 1 }.")
    assert t.args[1].name == "{}"
