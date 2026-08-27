import os
from warren.engine import Engine
from warren.pretty import term_to_str


def _engine():
    return Engine(backend="wam")


def solns(eng, q):
    return list(eng.query_text(q))


def _examples(name):
    return os.path.join(os.path.dirname(__file__), "..", "examples", name)


def test_append_and_backtracking():
    eng = _engine()
    sols = solns(eng, "append(X,Y,[1,2,3]).")
    assert len(sols) == 4
    assert term_to_str(sols[1]["X"]) == "[1]"


def test_cut_via_wam():
    eng = _engine()
    eng.consult_string("p(1). p(2). p(3). q(X) :- p(X), !.")
    sols = solns(eng, "findall(X, q(X), L).")
    assert term_to_str(sols[0]["L"]) == "[1]"


def test_if_then_else_via_wam():
    eng = _engine()
    eng.consult_string("classify(X,neg) :- X<0,!. classify(0,zero) :- !. classify(X,pos).")
    assert term_to_str(solns(eng, "classify(-3,C).")[0]["C"]) == "neg"
    assert term_to_str(solns(eng, "classify(5,C).")[0]["C"]) == "pos"


def test_disjunction_all_branches():
    eng = _engine()
    eng.consult_string("d(X) :- (X=a;X=b;X=c).")
    sols = solns(eng, "findall(X,d(X),L).")
    assert term_to_str(sols[0]["L"]) == "[a,b,c]"


def test_nested_nondeterminism_select():
    eng = _engine()
    eng.consult_string("two(L,X,Y) :- select(X,L,R), select(Y,R,_).")
    sols = solns(eng, "two([1,2,3],X,Y).")
    pairs = {(term_to_str(s["X"]), term_to_str(s["Y"])) for s in sols}
    assert len(sols) == 6
    assert ("1", "2") in pairs and ("3", "2") in pairs


def test_permutation_count():
    eng = _engine()
    sols = solns(eng, "findall(P, permutation([1,2,3],P), L), length(L,N).")
    assert term_to_str(sols[0]["N"]) == "6"


def test_negation_and_catch():
    eng = _engine()
    assert len(solns(eng, "\\+ member(a,[a,b,c]).")) == 0
    assert len(solns(eng, "\\+ member(z,[a,b,c]).")) == 1
    sols = solns(eng, "catch(X is 1/0, error(evaluation_error(zero_divisor),_), X=caught).")
    assert term_to_str(sols[0]["X"]) == "caught"


def test_assert_retract_via_wam():
    eng = _engine()
    eng.consult_string(":- dynamic(counter/1). counter(0).")
    for _ in range(5):
        list(eng.query_text("retract(counter(X)), X1 is X+1, assertz(counter(X1))."))
    assert term_to_str(solns(eng, "counter(X).")[0]["X"]) == "5"


def test_queens_matches_known_counts():
    eng = _engine()
    eng.consult_file(_examples("queens.pl"))
    assert term_to_str(solns(eng, "count_solutions(4,C).")[0]["C"]) == "2"
    assert term_to_str(solns(eng, "count_solutions(6,C).")[0]["C"]) == "4"


def test_zebra_puzzle_matches_published_answer():
    eng = _engine()
    eng.consult_file(_examples("zebra.pl"))
    sols = solns(eng, "zebra(Owner, WaterDrinker, Street).")
    assert len(sols) == 1
    assert term_to_str(sols[0]["Owner"]) == "japanese"
    assert term_to_str(sols[0]["WaterDrinker"]) == "norwegian"


def test_first_argument_indexing_avoids_backtracking_into_wrong_clause():
    eng = _engine()
    eng.consult_string("f(a, 1). f(b, 2). f(c, 3).")
    assert term_to_str(solns(eng, "f(b, X).")[0]["X"]) == "2"


def test_deep_recursion_no_python_recursion_error():
    eng = _engine()
    eng.consult_string("count(0) :- !. count(N) :- N > 0, N1 is N - 1, count(N1).")
    sols = solns(eng, "count(20000).")
    assert len(sols) == 1
