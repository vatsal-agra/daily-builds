"""Regression tests for bugs found during Phase 3's adversarial review
(see REVIEW.md for the full write-up of each)."""
import os
import subprocess
import sys

from warren.engine import Engine
from warren.pretty import term_to_str


def _engines():
    return Engine(backend="wam"), Engine(backend="golden")


def test_int_float_not_structurally_equal():
    for eng in _engines():
        assert list(eng.query_text("1 == 1.0.")) == []
        assert list(eng.query_text("1.0 == 1.0.")) != []
        assert list(eng.query_text("1 =:= 1.0.")) != []  # arithmetic equality IS true


def test_int_float_standard_order_distinguishes_type():
    for eng in _engines():
        sols = list(eng.query_text("compare(Order, 1.0, 1)."))
        assert term_to_str(sols[0]["Order"]) == "<"


def test_naf_side_effects_survive_backtracking():
    # \+ undoes bindings, but assert/retract are logical-update-view
    # database mutations, not trail entries -- they must NOT be undone.
    for eng in _engines():
        eng.consult_string(":- dynamic(seen/1).")
        list(eng.query_text("\\+ (assertz(seen(x)), fail)."))
        sols = list(eng.query_text("seen(X)."))
        assert len(sols) == 1 and term_to_str(sols[0]["X"]) == "x"


def test_cut_inside_findall_goal_is_scoped_to_findall():
    for eng in _engines():
        eng.consult_string("p(1). p(2). p(3).")
        sols = list(eng.query_text("findall(Y, (p(Y), Y>1, !), L)."))
        assert term_to_str(sols[0]["L"]) == "[2]"


def test_deep_list_no_recursion_error_within_limits():
    eng = Engine(backend="wam")
    eng.consult_string("mylen([],0). mylen([_|T],N) :- mylen(T,N0), N is N0+1.")
    n = 4000
    lst = "[" + ",".join(str(i) for i in range(n)) + "]"
    sols = list(eng.query_text(f"mylen({lst},C)."))
    assert term_to_str(sols[0]["C"]) == str(n)


def test_undefined_predicate_raises_existence_error_not_silent_failure():
    for eng in _engines():
        try:
            list(eng.query_text("this_is_not_defined_anywhere(1)."))
            assert False, "expected a PrologError"
        except Exception as e:
            assert "existence_error" in str(e)


def _run_cli(args, cwd):
    return subprocess.run([sys.executable, "-m", "warren"] + args,
                           cwd=cwd, capture_output=True, text=True, timeout=30)


def test_cli_reports_clean_error_for_missing_file(tmp_path):
    root = os.path.join(os.path.dirname(__file__), "..")
    r = _run_cli(["run", str(tmp_path / "does_not_exist.pl"), "true."], root)
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    assert "no such file" in r.stderr


def test_cli_reports_clean_error_for_syntax_error(tmp_path):
    bad = tmp_path / "bad.pl"
    bad.write_text("foo(X) :- bar(X\n")
    root = os.path.join(os.path.dirname(__file__), "..")
    r = _run_cli(["run", str(bad), "true."], root)
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    assert "syntax error" in r.stderr


def test_cli_reports_clean_error_for_undefined_predicate(tmp_path):
    ok = tmp_path / "ok.pl"
    ok.write_text("foo(1).\n")
    root = os.path.join(os.path.dirname(__file__), "..")
    r = _run_cli(["run", str(ok), "bar(X)."], root)
    assert r.returncode != 0
    assert "Traceback" not in r.stderr
    assert "existence_error" in r.stderr


def test_cli_long_list_via_big_stack_thread(tmp_path):
    src = tmp_path / "biglist.pl"
    src.write_text("mylen([],0).\nmylen([_|T],N) :- mylen(T,N0), N is N0+1.\n")
    n = 20000
    lst = "[" + ",".join(str(i) for i in range(n)) + "]"
    root = os.path.join(os.path.dirname(__file__), "..")
    r = _run_cli(["run", str(src), f"mylen({lst},C)."], root)
    assert r.returncode == 0
    assert f"C = {n}" in r.stdout
