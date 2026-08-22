"""One test per REVIEW.md finding that isn't already covered inline by a
more naturally-placed test elsewhere. See REVIEW.md for the full writeup of
each; the docstring on every test here names which finding it guards.

Findings covered elsewhere instead of here (cross-referenced, not
duplicated): #2 (nth0/nth1 bidirectionality) -> test_engine.py
test_nth0_forward_and_backward; #4 (directive parse crash) -> test_engine.py
test_directive_runs_immediately...; #5 (trailing-garbage syntax error) ->
test_parser.py test_syntax_error_on_trailing_garbage, and
test_cli.py test_query_syntax_error_exits_cleanly_no_traceback /
test_repl_rejects_malformed_query_cleanly; #7, #8, #9 (the visualizer
findings) -> test_viz.py.
"""

from horn.engine import make_engine
from horn.parser import parse_term
from horn.repl import query_vars
from horn.terms import format_term
from horn.unify import undo_to


def test_finding_1_query_vars_handles_a_long_list_without_recursion_error():
    """#1: query_vars used to recurse over the raw term tree and blew the
    Python stack on a query built from a long list literal, before the
    query ever reached the engine's own big-stack thread."""
    items = "[" + ",".join(str(i) for i in range(8000)) + "]"
    goal = parse_term(f"length({items}, N).")
    vs = query_vars(goal)  # must not raise RecursionError
    assert [v.name for v in vs] == ["N"]


def test_finding_3_cyclic_term_prints_instead_of_crashing():
    """#3: printing a cyclic term (built when the occurs check is off,
    which is the default) used to crash with a raw RecursionError instead
    of the intended graceful truncation."""
    eng = make_engine()
    goal = parse_term("X = f(X).")
    list(eng.solve_top(goal))  # binds X into a cyclic term
    text = format_term(goal)  # must not raise
    assert text.endswith("...") is False  # the guard applies inside f(...), not at top level
    assert len(text) < 5000  # bounded, not runaway


def test_finding_6_abandoned_query_does_not_leak_the_trail():
    """#6: taking only the first solution of a query (the common case)
    abandons its solve() generator before it runs its own post-yield
    undo_to(), leaking a few trail entries per query forever in a
    long-lived Engine (exactly the REPL's usage pattern). The fix is at
    the CLI/REPL call sites (they now bracket every top-level query with
    their own mark/undo), not in the engine itself -- so this test
    reproduces the fix's own pattern directly."""
    eng = make_engine()
    eng.consult_text("p(1). p(2). p(3).")
    for _ in range(50):
        goal = parse_term("member(X, [1,2,3,4,5]).")
        mark = len(eng.trail)
        for _ in eng.solve_top(goal):
            break  # abandon after the first solution, like the CLI/REPL do
        undo_to(eng.trail, mark)  # the fix cli.py/repl.py both apply
    assert len(eng.trail) == 0
