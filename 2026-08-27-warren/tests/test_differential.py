"""The oracle check central to Warren's design: the compiled WAM and the
independent tree-walking golden-model interpreter must agree, solution
for solution, on every query here."""
import os
import re
import pytest
from warren.engine import Engine
from warren.pretty import term_to_str


PROGRAM = """
append_(  [],   L,  L).
append_([H|T],  L, [H|R]) :- append_(T, L, R).

fact(0,1) :- !.
fact(N,F) :- N>0, N1 is N-1, fact(N1,F1), F is N*F1.

fib(0,0) :- !.
fib(1,1) :- !.
fib(N,F) :- N>1, N1 is N-1, N2 is N-2, fib(N1,F1), fib(N2,F2), F is F1+F2.

max3(X,Y,Z,M) :- X>=Y, X>=Z, !, M=X.
max3(X,Y,Z,M) :- Y>=X, Y>=Z, !, M=Y.
max3(_,_,Z,Z).

parent(tom,bob). parent(tom,liz). parent(bob,ann). parent(bob,pat).
parent(pat,jim). parent(alice,bob).
ancestor(A,D) :- parent(A,D).
ancestor(A,D) :- parent(A,P), ancestor(P,D).

evenlist([]).
evenlist([_,_|T]) :- evenlist(T).

:- dynamic(seen/1).
mark(X) :- ( seen(X) -> true ; assertz(seen(X)) ).
"""

QUERIES = [
    "append_(X,Y,[1,2,3]).",
    "append_([1,2],[3,4],Z).",
    "fact(10,F).",
    "fib(15,F).",
    "max3(3,7,5,M).",
    "max3(9,2,5,M).",
    "findall(X, ancestor(tom,X), L).",
    "ancestor(alice,jim).",
    "\\+ ancestor(jim,tom).",
    "evenlist([a,b,c,d]).",
    "\\+ evenlist([a,b,c]).",
    "(member(X,[1,2,3]) -> Y=found ; Y=missing).",
    "(member(X,[]) -> Y=found ; Y=missing).",
    "findall(X-Y, (member(X,[1,2]),member(Y,[a,b])), L).",
    "sort([3,1,2,3,1],L).",
    "msort([3,1,2,3,1],L).",
    "catch(throw(oops), oops, R=caught).",
    "catch((X is 1/0), error(evaluation_error(zero_divisor),_), X=safe).",
    "mark(a), mark(b), mark(a), findall(X,seen(X),L).",
    "atom_concat(foo,bar,X).",
    "( X = 1 ; X = 2 ; X = 3 ).",
    "permutation([1,2,3],P).",
    "select(X,[a,b,c],R).",
    "length(L,3).",
    "between(1,5,X).",
    "\\+ \\+ member(a,[a,b]).",
]


def _examples(name):
    return os.path.join(os.path.dirname(__file__), "..", "examples", name)


_VAR_RE = re.compile(r"_[A-Za-z0-9_]*")


def _normalize(sol):
    """Both backends print an unbound var using its own internal name
    (golden keeps the source name; the WAM's reifier invents `_H<addr>`
    names for heap cells) -- collapse any such printed name (including
    ones nested inside a list/struct) to one placeholder so cross-engine
    comparison checks *boundness*, not the cosmetic label of an unbound
    variable."""
    return {k: _VAR_RE.sub("_VAR", term_to_str(v)) for k, v in sol.items()}


@pytest.fixture
def engines():
    wam = Engine(backend="wam")
    gold = Engine(backend="golden")
    wam.consult_string(PROGRAM)
    gold.consult_string(PROGRAM)
    return wam, gold


@pytest.mark.parametrize("q", QUERIES)
def test_wam_matches_golden(engines, q):
    wam, gold = engines
    ws = [_normalize(s) for s in wam.query_text(q)]
    gs = [_normalize(s) for s in gold.query_text(q)]
    assert ws == gs, f"mismatch for {q!r}: wam={ws} golden={gs}"


@pytest.mark.parametrize("filename,query", [
    ("queens.pl", "count_solutions(6,C)."),
    ("zebra.pl", "zebra(Owner,WaterDrinker,Street)."),
])
def test_example_programs_agree(filename, query):
    wam = Engine(backend="wam")
    gold = Engine(backend="golden")
    wam.consult_file(_examples(filename))
    gold.consult_file(_examples(filename))
    ws = [{k: term_to_str(v) for k, v in s.items()} for s in wam.query_text(query)]
    gs = [{k: term_to_str(v) for k, v in s.items()} for s in gold.query_text(query)]
    assert ws == gs
