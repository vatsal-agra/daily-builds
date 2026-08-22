import pytest

from conftest import fails, solutions, succeeds
from horn.engine import make_engine
from horn.errors import HornError
from horn.parser import parse_term
from horn.runstack import run_with_stack


def test_facts_and_backtracking(engine):
    engine.consult_text("p(1). p(2). p(3).")
    assert solutions(engine, "p(X).") == ["X = 1.", "X = 2.", "X = 3."]


def test_conjunction_and_rules(engine):
    engine.consult_text("p(1). p(2). q(X) :- p(X), X > 1.")
    assert solutions(engine, "q(X).") == ["X = 2."]


def test_cut_commits_to_first_matching_clause(engine):
    engine.consult_text("p(1). p(2). p(3). first(X) :- p(X), !.")
    assert solutions(engine, "first(X).") == ["X = 1."]


def test_cut_prevents_retrying_earlier_alternatives_after_a_later_failure(engine):
    # Classic tricky case: after the cut commits to a(2), the following
    # `fail` must NOT reopen a/1's remaining alternative (a(3)).
    engine.consult_text("a(1). a(2). a(3). b(X) :- a(X), X > 1, !, fail.")
    assert solutions(engine, "b(X).") == []


def test_cut_does_not_escape_into_the_caller(engine):
    engine.consult_text(
        """
        inner(X) :- member(X, [1,2,3]), X > 1, !.
        outer(Y) :- inner(Y).
        outer(other).
        """
    )
    assert solutions(engine, "outer(Y).") == ["Y = 2.", "Y = other."]


def test_negation_as_failure(engine):
    engine.consult_text("p(1). p(2).")
    assert succeeds(engine, "\\+ p(3).")
    assert fails(engine, "\\+ p(1).")


def test_negation_does_not_bind_variables(engine):
    engine.consult_text("p(1).")
    # A variable unrelated to the negated goal must stay untouched by it.
    assert solutions(engine, "\\+ p(99), Y = free.") == ["Y = free."]
    # An unbound variable *inside* the negated goal is existentially
    # quantified there, per standard negation-as-failure semantics: \+ p(X)
    # asks "does p(X) have no solution for *any* X", which is false here
    # since p(1) exists -- so this must fail, matching real Prolog.
    assert fails(engine, "\\+ p(X), X = free.")


def test_negation_is_opaque_to_cut(engine):
    # A cut inside \+ must not escape and commit the *caller's* choice.
    engine.consult_text("p(1). p(2). q(X) :- p(X), \\+ (X =:= 1, !).")
    assert solutions(engine, "q(X).") == ["X = 2."]


def test_unify_and_not_unifiable(engine):
    assert succeeds(engine, "f(X,1) = f(2,Y).")
    assert fails(engine, "1 \\= 1.")
    assert succeeds(engine, "1 \\= 2.")


def test_structural_equality_vs_arithmetic_equality(engine):
    assert succeeds(engine, "3 =:= 3.0.")
    assert fails(engine, "3 = 3.0.")
    assert fails(engine, "3 == 3.0.")


def test_arithmetic(engine):
    assert solutions(engine, "X is 1 + 2 * 3.") == ["X = 7."]
    assert solutions(engine, "X is 7 // 2.") == ["X = 3."]
    assert solutions(engine, "X is -7 // 2.") == ["X = -4."]
    assert solutions(engine, "X is 7 mod 3.") == ["X = 1."]
    assert solutions(engine, "X is -7 mod 3.") == ["X = 2."]


def test_is_on_unbound_var_raises(engine):
    with pytest.raises(HornError):
        list(engine.solve_top(parse_term("X is Y + 1.")))


def test_unknown_predicate_raises_existence_error(engine):
    with pytest.raises(HornError, match="existence_error"):
        list(engine.solve_top(parse_term("nope(1,2).")))


def test_type_checks(engine):
    engine.consult_text("")
    assert succeeds(engine, "var(X).")
    assert fails(engine, "var(a).")
    assert succeeds(engine, "atom(a).")
    assert succeeds(engine, "number(1).")
    assert succeeds(engine, "is_list([1,2,3]).")
    assert fails(engine, "is_list([1|foo]).")


def test_findall(engine):
    import re

    engine.consult_text("p(1). p(2). p(3).")
    # X is both findall's template and a top-level query variable here, so
    # (matching real Prolog) it's reported too -- findall/3 doesn't bind it
    # outside the aggregation, only L. The fresh variable's printed name
    # carries a non-deterministic unique id (see terms.format_term), so
    # match the shape, not an exact string.
    [sol] = solutions(engine, "findall(X, p(X), L).")
    assert re.fullmatch(r"X = _X\d+, L = \[1, 2, 3\]\.", sol)
    [sol2] = solutions(engine, "findall(Y, (p(Y), Y > 5), L).")
    assert re.fullmatch(r"Y = _Y\d+, L = \[\]\.", sol2)


def test_findall_uses_fresh_variables_per_solution(engine):
    # An unbound template variable must get a genuinely distinct fresh copy
    # per collected solution (copy_term/2 semantics), not the same Var
    # object aliased across all of them -- checked by identity via the
    # engine's own terms, not by comparing printed text (two independent
    # fresh vars can print with the same *name* but must carry different
    # unique ids; see terms.format_term).
    import re

    from horn.terms import deref, format_term, list_to_python

    engine.consult_text("p(1). p(2).")
    goal = parse_term("findall(f(X,Y), p(X), L).")  # goal.args = (Template, Goal, L)
    sol_iter = engine.solve_top(goal)
    next(sol_iter)  # take (and stop at) the one solution -- findall/3 is
    # deterministic, but exhausting the generator (e.g. via list(...))
    # would resume past its yield into its own post-solution undo_to(),
    # unbinding L again before we get a chance to inspect it.
    items = list_to_python(deref(goal.args[2]))
    assert len(items) == 2
    y_vars = [deref(deref(item).args[1]) for item in items]
    assert y_vars[0] is not y_vars[1]  # distinct fresh Var objects
    for item in items:
        assert re.fullmatch(r"f\(\d, _Y\d+\)", format_term(item))


def test_occurs_check_flag():
    on = make_engine(occurs_check=True)
    assert fails(on, "X = f(X).")
    off = make_engine(occurs_check=False)
    assert succeeds(off, "X = f(X).")


def test_directive_runs_immediately_and_fails_cleanly_if_unsatisfiable():
    ok_engine = make_engine()
    ok_engine.consult_text("p(1).\n:- p(1).\n")  # must not raise
    bad_engine = make_engine()
    with pytest.raises(HornError):
        bad_engine.consult_text(":- p(999).\np(1).\n")


# -- stdlib predicates --------------------------------------------------


def test_append_generate_and_split(engine):
    assert solutions(engine, "append([1,2],[3],L).") == ["L = [1, 2, 3]."]
    assert len(solutions(engine, "append(X,Y,[1,2,3]).")) == 4


def test_member(engine):
    assert solutions(engine, "member(X,[a,b,c]).") == ["X = a.", "X = b.", "X = c."]


def test_length(engine):
    assert solutions(engine, "length([a,b,c],N).") == ["N = 3."]


def test_reverse(engine):
    assert solutions(engine, "reverse([1,2,3],R).") == ["R = [3, 2, 1]."]


def test_nth0_forward_and_backward(engine):
    assert solutions(engine, "nth0(1,[a,b,c],X).") == ["X = b."]
    # Regression for REVIEW.md finding #2: must search, not raise, when the
    # index is unbound and the element is given instead.
    assert solutions(engine, "nth0(N,[a,b,c],b).") == ["N = 1."]


def test_nth1_forward_and_backward(engine):
    assert solutions(engine, "nth1(1,[a,b,c],X).") == ["X = a."]
    assert solutions(engine, "nth1(N,[a,b,c],c).") == ["N = 3."]


def test_select_insert_mode(engine):
    sols = solutions(engine, "select(3,L,[1,2,4]).")
    assert len(sols) == 4  # 3 can be inserted at any of 4 positions


def test_permutation_count(engine):
    assert len(solutions(engine, "permutation([1,2,3],P).")) == 6


def test_numlist(engine):
    assert solutions(engine, "numlist(1,5,L).") == ["L = [1, 2, 3, 4, 5]."]
    assert solutions(engine, "numlist(5,1,L).") == ["L = []."]  # empty range, one clean answer


def test_max_list_min_list(engine):
    assert solutions(engine, "max_list([3,1,4,1,5,9,2,6],M).") == ["M = 9."]
    assert solutions(engine, "min_list([3,1,4,1,5,9,2,6],M).") == ["M = 1."]


def test_sum_list(engine):
    assert solutions(engine, "sum_list([1,2,3,4],S).") == ["S = 10."]


def test_adjacent_both_orders(engine):
    assert succeeds(engine, "adjacent(a,b,[a,b,c]).")
    assert succeeds(engine, "adjacent(b,a,[a,b,c]).")
    assert fails(engine, "adjacent(a,c,[a,b,c]).")


# -- deep recursion / the big-stack thread -------------------------------


def test_deep_recursion_completes_via_runstack():
    eng = make_engine()
    items = "[" + ",".join(str(i) for i in range(3000)) + "]"
    goal = parse_term(f"length({items}, N).")

    def work():
        for _ in eng.solve_top(goal):
            return True
        return False

    assert run_with_stack(work) is True


def test_pathological_recursion_fails_cleanly_not_a_segfault():
    # Comfortably past the ~10,000-call safety margin runstack.py documents.
    # A literal list (not numlist/3, which is itself recursive and would
    # make *building* the input the slow part) keeps this test fast.
    eng = make_engine()
    items = "[" + ",".join(str(i) for i in range(25000)) + "]"
    goal = parse_term(f"length({items}, N).")

    def work():
        for _ in eng.solve_top(goal):
            return True
        return False

    with pytest.raises(RecursionError):
        run_with_stack(work)
