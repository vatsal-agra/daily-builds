"""`horn demo`: a narrated, assertion-checked walkthrough of every required
and stretch feature, run against the real engine (not mocked/pretend
output). Exits non-zero if anything doesn't match its expected, independently
verifiable answer."""

import os

from .engine import make_engine
from .parser import parse_term
from .repl import format_solution, query_vars
from .terms import format_term

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")

_failures = []


def check(label, condition):
    status = "ok" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        _failures.append(label)


def run_query(engine, text, cap=1000):
    goal = parse_term(text)
    vars_ = query_vars(goal)
    out = []
    for _ in engine.solve_top(goal):
        out.append(format_solution(vars_))
        if len(out) >= cap:
            break
    return out


def section(title):
    print(f"\n=== {title} ===")


def run_demo():
    section("1. Parser: facts, rules, lists, operators")
    eng = make_engine()
    eng.consult_text("p(1). p(2). p(3). q(X) :- p(X), X > 1.")
    check("facts backtrack in source order", run_query(eng, "p(X).") == ["X = 1.", "X = 2.", "X = 3."])
    check("rule with a conjunction body", run_query(eng, "q(X).") == ["X = 2.", "X = 3."])
    t = parse_term("X is 1 + 2 * 3.").args[1]
    check("operator precedence: 1 + 2*3 groups as +(1,*(2,3))", t.functor == "+" and t.args[1].functor == "*")
    check("list syntax round-trips", format_term(parse_term("[1,2,3].")) == "[1, 2, 3]")

    section("2. Unification: trail-based backtracking + occurs check")
    on = make_engine()
    off = make_engine()
    check("occurs check off (default): X = f(X) succeeds", len(run_query(off, "X = f(X).", cap=1)) == 1)
    on2 = make_engine(occurs_check=True)
    check("occurs check on: X = f(X) fails", run_query(on2, "X = f(X).") == [])

    section("3. SLD resolution: cut and negation-as-failure")
    eng2 = make_engine()
    eng2.consult_text("a(1). a(2). a(3). first(X) :- a(X), !. cutfail(X) :- a(X), X > 1, !, fail.")
    check("cut commits to the first match", run_query(eng2, "first(X).") == ["X = 1."])
    check("cut+fail leaves no alternatives to retry", run_query(eng2, "cutfail(X).") == [])
    eng2.consult_text("p(1). p(2).")
    check("negation-as-failure", run_query(eng2, "\\+ p(3).") == ["true."])
    check("negation fails when the goal has a solution", run_query(eng2, "\\+ p(1).") == [])

    section("4. Builtins + Horn-native standard library")
    eng3 = make_engine()
    check("arithmetic + precedence", run_query(eng3, "X is 1 + 2 * 3.") == ["X = 7."])
    check("append splits a list every way", len(run_query(eng3, "append(X,Y,[1,2,3]).")) == 4)
    check("nth0 forward", run_query(eng3, "nth0(1,[a,b,c],X).") == ["X = b."])
    check("nth0 backward (search for the index)", run_query(eng3, "nth0(N,[a,b,c],b).") == ["N = 1."])
    [findall_sol] = run_query(eng3, "findall(Y,(member(Y,[1,2,3]),Y>1),L).")
    check("findall aggregates all solutions", findall_sol.endswith("L = [2, 3]."))

    section("5. Demo programs, checked against independently-known answers")
    fam = make_engine()
    with open(os.path.join(EXAMPLES, "family.horn"), encoding="utf-8") as f:
        fam.consult_text(f.read())
    check("family tree: tom is jim's ancestor", run_query(fam, "ancestor(tom, jim).") == ["true."])
    check("family tree: grandparent/2", run_query(fam, "grandparent(marge, X).") == ["X = ann.", "X = pat."])

    q = make_engine()
    with open(os.path.join(EXAMPLES, "queens.horn"), encoding="utf-8") as f:
        q.consult_text(f.read())
    n6 = run_query(q, "queens(6, Qs).")
    check("6-Queens has exactly 4 solutions (published count)", len(n6) == 4)

    mc = make_engine()
    with open(os.path.join(EXAMPLES, "map_coloring.horn"), encoding="utf-8") as f:
        mc.consult_text(f.read())
    colorings = run_query(mc, "australia(WA,NT,SA,Q,NSW,V,T).")
    check("Australia map coloring has 18 solutions (6 mainland x 3 for Tasmania)", len(colorings) == 18)

    zeb = make_engine()
    with open(os.path.join(EXAMPLES, "zebra.horn"), encoding="utf-8") as f:
        zeb.consult_text(f.read())
    check("Zebra puzzle: the Norwegian drinks water", run_query(zeb, "water_drinker(X).") == ["X = norwegian."])
    check("Zebra puzzle: the Japanese owns the zebra", run_query(zeb, "zebra_owner(X).") == ["X = japanese."])

    section("6. Stretch: SLD-resolution-tree visualizer matches the real engine")
    from .viz import build_trace

    fam2 = make_engine()
    with open(os.path.join(EXAMPLES, "family.horn"), encoding="utf-8") as f:
        fam2.consult_text(f.read())
    _, traced, truncated = build_trace(fam2, parse_term("ancestor(tom, X)."), max_solutions=10)
    check("tracer finds the same solutions as the real engine", traced == run_query(fam, "ancestor(tom, X)."))
    check("tracer did not need to truncate this search", not truncated)

    section("7. Deep recursion: fails cleanly, not a segfault")
    from .runstack import run_with_stack

    deep_eng = make_engine()
    big_list = "[" + ",".join(str(i) for i in range(3000)) + "]"
    goal = parse_term(f"length({big_list}, N).")

    def work():
        for _ in deep_eng.solve_top(goal):
            return True
        return False

    check("3,000-element list recursion completes via the big-stack thread", run_with_stack(work) is True)

    print()
    if _failures:
        print(f"DEMO FAILED: {len(_failures)} check(s) failed: {_failures}")
        return 1
    print("DEMO PASSED: all checks green.")
    return 0
