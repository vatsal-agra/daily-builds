"""Subprocess-driven tests against the real `horn` CLI -- exercises the
actual entry point a user runs, not just the Python API underneath it."""

import subprocess
import sys

from conftest import EXAMPLES

ROOT = EXAMPLES.rsplit("/examples", 1)[0]


def run_cli(*args, input_text=None, timeout=30):
    return subprocess.run(
        [sys.executable, "-m", "horn", *args],
        cwd=ROOT,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_query_single_solution():
    r = run_cli("query", "examples/family.horn", "ancestor(tom, jim).")
    assert r.returncode == 0
    assert r.stdout.strip() == "true."


def test_query_all_solutions():
    r = run_cli("query", "examples/family.horn", "grandparent(marge, X).", "--all")
    assert r.returncode == 0
    assert r.stdout.strip().splitlines() == ["X = ann.", "X = pat."]


def test_query_no_solution_exits_nonzero():
    r = run_cli("query", "examples/family.horn", "father(ann, X).")
    assert r.returncode == 1
    assert r.stdout.strip() == "false."


def test_query_syntax_error_exits_cleanly_no_traceback():
    r = run_cli("query", "examples/family.horn", "foo bar.")
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    assert "syntax_error" in r.stderr


def test_missing_file_exits_cleanly_no_traceback():
    r = run_cli("run", "examples/does_not_exist.horn")
    assert r.returncode == 1
    assert "Traceback" not in r.stderr


def test_run_without_query_just_consults():
    r = run_cli("run", "examples/family.horn")
    assert r.returncode == 0
    assert "consulted" in r.stdout


def test_occurs_check_flag():
    r = run_cli("--occurs-check", "query", "examples/family.horn", "X = f(X).")
    assert r.returncode == 1
    assert r.stdout.strip() == "false."


def test_zebra_via_cli_matches_known_answer():
    r = run_cli("query", "examples/zebra.horn", "water_drinker(X).")
    assert r.returncode == 0
    assert r.stdout.strip() == "X = norwegian."


def test_viz_writes_self_contained_html(tmp_path):
    import re

    out = tmp_path / "trace.html"
    r = run_cli("viz", "examples/family.horn", "-q", "ancestor(tom, X).", "--out", str(out))
    assert r.returncode == 0
    assert out.exists()
    content = out.read_text()
    assert "<script>" in content
    assert re.search(r"ancestor\(tom, _X\d+\)", content)


def test_repl_basic_session():
    r = run_cli(
        "repl",
        "examples/family.horn",
        input_text="member(X,[a,b,c]).\n;\n.\nhalt.\n",
        timeout=15,
    )
    assert "X = a." in r.stdout
    assert "X = b." in r.stdout
    assert "halt(0)" in r.stdout


def test_repl_rejects_malformed_query_cleanly():
    r = run_cli(
        "repl",
        "examples/family.horn",
        input_text="foo bar.\nhalt.\n",
        timeout=15,
    )
    assert "syntax_error" in r.stdout
    assert "Traceback" not in r.stdout
