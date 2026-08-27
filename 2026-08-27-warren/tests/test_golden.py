from warren.engine import Engine
from warren.pretty import term_to_str


def _engine():
    return Engine(backend="golden")


def solns(eng, q):
    return list(eng.query_text(q))


def test_append():
    eng = _engine()
    sols = solns(eng, "append([1,2],[3,4],X).")
    assert len(sols) == 1
    assert term_to_str(sols[0]["X"]) == "[1,2,3,4]"


def test_cut_commits_to_first_clause():
    eng = _engine()
    eng.consult_string("p(1). p(2). p(3). q(X) :- p(X), !.")
    sols = solns(eng, "findall(X, q(X), L).")
    assert term_to_str(sols[0]["L"]) == "[1]"


def test_if_then_else():
    eng = _engine()
    eng.consult_string("classify(X,neg) :- X<0,!. classify(0,zero) :- !. classify(X,pos).")
    assert term_to_str(solns(eng, "classify(-3,C).")[0]["C"]) == "neg"
    assert term_to_str(solns(eng, "classify(0,C).")[0]["C"]) == "zero"
    assert term_to_str(solns(eng, "classify(5,C).")[0]["C"]) == "pos"


def test_negation_as_failure():
    eng = _engine()
    assert len(solns(eng, "\\+ member(x,[a,b,c]).")) == 1
    assert len(solns(eng, "\\+ member(a,[a,b,c]).")) == 0


def test_findall_and_arithmetic():
    eng = _engine()
    sols = solns(eng, "findall(Y, (member(X,[1,2,3]), Y is X*X), L).")
    assert term_to_str(sols[0]["L"]) == "[1,4,9]"


def test_assert_retract():
    eng = _engine()
    eng.consult_string(":- dynamic(counter/1). counter(0).")
    list(eng.query_text("retract(counter(X)), X1 is X+1, assertz(counter(X1))."))
    assert term_to_str(solns(eng, "counter(X).")[0]["X"]) == "1"


def test_catch_throw():
    eng = _engine()
    sols = solns(eng, "catch(X is 1/0, error(evaluation_error(zero_divisor),_), X=caught).")
    assert term_to_str(sols[0]["X"]) == "caught"


def test_standard_order_and_sort():
    eng = _engine()
    sols = solns(eng, "sort([3,1,2,1],L).")
    assert term_to_str(sols[0]["L"]) == "[1,2,3]"


def test_queens4():
    eng = _engine()
    eng.consult_file(_examples("queens.pl"))
    sols = solns(eng, "count_solutions(4,C).")
    assert term_to_str(sols[0]["C"]) == "2"


def _examples(name):
    import os
    return os.path.join(os.path.dirname(__file__), "..", "examples", name)
