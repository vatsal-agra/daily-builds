"""`horn` command-line interface."""

import argparse
import sys

from .engine import make_engine
from .errors import HaltSignal, HornError
from .parser import parse_term
from .repl import format_solution, query_vars
from .runstack import run_with_stack


def cmd_run(args):
    engine = make_engine(occurs_check=args.occurs_check)
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            engine.consult_text(f.read())
    if not args.query:
        print(f"consulted {', '.join(args.files)}; no query given, nothing to run")
        return 0
    return _run_query(engine, args.query, args.all)


def cmd_query(args):
    engine = make_engine(occurs_check=args.occurs_check)
    with open(args.file, encoding="utf-8") as f:
        engine.consult_text(f.read())
    return _run_query(engine, args.goal, args.all)


def _run_query(engine, goal_text, show_all):
    try:
        goal = parse_term(goal_text)
    except HornError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    vars_ = query_vars(goal)
    found = [0]

    def work():
        for _ in engine.solve_top(goal):
            found[0] += 1
            print(format_solution(vars_))
            if not show_all:
                break

    try:
        run_with_stack(work)
    except HaltSignal as h:
        return h.code
    except HornError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except RecursionError:
        print("error: recursion depth exceeded (query too deep)", file=sys.stderr)
        return 1
    if found[0] == 0:
        print("false.")
        return 1
    return 0


def cmd_repl(args):
    from .repl import run_repl

    run_repl(args.files, occurs_check=args.occurs_check, trace=args.trace)
    return 0


def cmd_viz(args):
    from .viz import render_trace_html

    engine = make_engine(occurs_check=args.occurs_check)
    for path in args.files:
        with open(path, encoding="utf-8") as f:
            engine.consult_text(f.read())
    goal = parse_term(args.query)
    html = render_trace_html(engine, goal, max_solutions=args.max_solutions)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {args.out}")
    return 0


def cmd_demo(args):
    from .demo import run_demo

    return run_demo()


def cmd_test(args):
    import subprocess
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=root)
    return result.returncode


def build_parser():
    p = argparse.ArgumentParser(prog="horn", description="A miniature Prolog-family logic-programming language.")
    p.add_argument("--occurs-check", action="store_true", help="enable the occurs check in unification")
    sub = p.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="consult one or more .horn files, optionally run a query")
    p_run.add_argument("files", nargs="+")
    p_run.add_argument("--query", "-q", help="a goal to solve after consulting")
    p_run.add_argument("--all", action="store_true", help="print every solution instead of just the first")
    p_run.set_defaults(func=cmd_run)

    p_query = sub.add_parser("query", help="consult one file and run one query")
    p_query.add_argument("file")
    p_query.add_argument("goal")
    p_query.add_argument("--all", action="store_true")
    p_query.set_defaults(func=cmd_query)

    p_repl = sub.add_parser("repl", help="interactive top-level")
    p_repl.add_argument("files", nargs="*")
    p_repl.add_argument("--trace", action="store_true")
    p_repl.set_defaults(func=cmd_repl)

    p_viz = sub.add_parser("viz", help="render an interactive HTML SLD-resolution-tree for a query")
    p_viz.add_argument("files", nargs="+")
    p_viz.add_argument("--query", "-q", required=True, dest="query")
    p_viz.add_argument("--out", "-o", default="horn_trace.html")
    p_viz.add_argument("--max-solutions", type=int, default=5)
    p_viz.set_defaults(func=cmd_viz)

    p_demo = sub.add_parser("demo", help="run the built-in end-to-end feature walkthrough")
    p_demo.set_defaults(func=cmd_demo)

    p_test = sub.add_parser("test", help="run the pytest suite")
    p_test.set_defaults(func=cmd_test)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except HornError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
