"""The visualizer (horn/viz.py) runs its own tracing evaluator rather than
instrumenting the reviewed engine.py hot path directly, so its correctness
rests entirely on this file: does it find the exact same solutions, in the
same order, as the real engine? If this ever goes red, the picture the
visualizer draws is lying about what the engine actually does."""

import os

import pytest

from conftest import EXAMPLES, consult_example
from horn.engine import make_engine
from horn.parser import parse_term
from horn.repl import format_solution, query_vars
from horn.viz import build_trace, render_trace_html


def real_solutions(engine, goal, cap):
    vars_ = query_vars(goal)
    out = []
    for _ in engine.solve_top(goal):
        out.append(format_solution(vars_))
        if len(out) >= cap:
            break
    return out


CASES = [
    ("family.horn", "ancestor(tom, X).", 10),
    ("family.horn", "sibling(X, Y).", 10),
    ("family.horn", "grandparent(marge, X).", 10),
    ("queens.horn", "queens(4, Qs).", 10),
    ("queens.horn", "queens(5, Qs).", 3),
    ("map_coloring.horn", "australia(WA,NT,SA,Q,NSW,V,T).", 4),
]


@pytest.mark.parametrize("filename,query,cap", CASES)
def test_tracer_matches_real_engine(filename, query, cap):
    eng_real = make_engine()
    consult_example(eng_real, filename)
    eng_trace = make_engine()
    consult_example(eng_trace, filename)

    real = real_solutions(eng_real, parse_term(query), cap)
    _, traced, truncated = build_trace(eng_trace, parse_term(query), max_solutions=cap)

    assert traced == real
    assert not truncated


def test_solution_cap_is_actually_enforced():
    # Regression for REVIEW.md finding #7: the cap was checked but never
    # incremented, so it silently never engaged (it would keep exploring
    # until the much larger node cap eventually, coincidentally, stopped
    # it instead). family.horn's ancestor/2 has 5 real solutions and a
    # small search tree, so a cap of 2 unambiguously demonstrates the cap
    # itself is what stops the search, not an unrelated node-budget limit.
    eng = make_engine()
    consult_example(eng, "family.horn")
    _, traced, truncated = build_trace(eng, parse_term("ancestor(tom, X)."), max_solutions=2)
    assert len(traced) == 2
    assert traced == ["X = bob.", "X = liz."]


def test_query_variables_unbound_after_tracing():
    # Regression for REVIEW.md finding #8: build_trace must not leave the
    # query's own variables bound to the last-explored branch.
    import re

    eng = make_engine()
    consult_example(eng, "family.horn")
    goal = parse_term("ancestor(tom, X).")
    build_trace(eng, goal, max_solutions=5)
    from horn.terms import format_term

    # The var's printed name carries a non-deterministic unique id (see
    # terms.format_term), so match the shape rather than an exact string.
    assert re.fullmatch(r"ancestor\(tom, _X\d+\)", format_term(goal))


def test_render_produces_self_contained_html():
    import re

    eng = make_engine()
    consult_example(eng, "family.horn")
    html = render_trace_html(eng, parse_term("ancestor(tom, X)."))
    assert "<script>" in html and "</html>" in html
    # the query itself, not a stale bound-to-the-last-solution value
    assert re.search(r"ancestor\(tom, _X\d+\)", html)
    assert "http://" not in html and "https://" not in html  # no external assets


def test_truncation_is_reported_not_hidden():
    eng = make_engine()
    consult_example(eng, "queens.horn")
    _, _, truncated = build_trace(
        eng, parse_term("queens(7, Qs)."), max_solutions=100, max_nodes=200
    )
    assert truncated is True


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_rendered_page_loads_without_js_errors_in_real_chromium(theme, tmp_path):
    # Regression for REVIEW.md finding #9: a real browser enforces things a
    # cursory read of the generated JS does not catch (DOMTokenList.add('')
    # throws in Chromium). Skips gracefully if Playwright/Chromium aren't
    # available in this environment rather than failing the whole suite.
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    chromium_path = "/opt/pw-browsers/chromium"
    if not os.path.exists(chromium_path):
        pytest.skip("no pre-installed Chromium in this environment")

    eng = make_engine()
    consult_example(eng, "family.horn")
    html = render_trace_html(eng, parse_term("ancestor(tom, X)."))
    out_file = tmp_path / "trace.html"
    out_file.write_text(html, encoding="utf-8")

    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium_path)
        page = browser.new_page(color_scheme=theme)
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(out_file.as_uri())
        page.wait_for_timeout(200)
        tree_html = page.eval_on_selector("#tree", "el => el.innerHTML")
        browser.close()

    assert errors == []
    assert len(tree_html) > 0
