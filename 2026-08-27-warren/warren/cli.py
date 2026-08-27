"""Warren's command-line interface."""
import argparse
import sys

from .engine import Engine
from .pretty import term_to_str
from .errors import PrologError


def cmd_run(args):
    eng = Engine(backend=args.backend)
    eng.consult_file(args.file)
    if args.goal:
        _run_goal(eng, args.goal, all_solutions=args.all)
    return 0


def _run_goal(eng, goal_text, all_solutions=False):
    try:
        found = False
        for sol in eng.query_text(goal_text):
            found = True
            if sol:
                print("  " + ", ".join(f"{k} = {term_to_str(v, quoted=True)}" for k, v in sol.items()))
            else:
                print("  true.")
            if not all_solutions:
                break
        if not found:
            print("false.")
    except PrologError as e:
        print(f"error: {term_to_str(e.term, quoted=True)}", file=sys.stderr)
        return 1
    return 0


def cmd_repl(args):
    eng = Engine(backend=args.backend)
    if args.file:
        eng.consult_file(args.file)
    print("Warren -- a Prolog on a real WAM. ':- halt.' or Ctrl-D to exit.")
    while True:
        try:
            line = input("?- ")
        except EOFError:
            print()
            break
        line = line.strip()
        if not line:
            continue
        if not line.endswith("."):
            line += "."
        try:
            from .parser import Parser
            p = Parser(line)
            term = p.read_clause()
            from .terms import Struct, deref
            t = deref(term)
            if isinstance(t, Struct) and t.name == ":-" and t.arity == 1:
                goal = t.args[0]
            else:
                goal = term
            found = False
            gen = eng.query_term(goal)
            for sol in gen:
                found = True
                if sol:
                    print(", ".join(f"{k} = {term_to_str(v, quoted=True)}" for k, v in sol.items()), end="")
                else:
                    print("true", end="")
                try:
                    more = input(" ? (;/./enter for next, . to stop) ").strip()
                except EOFError:
                    more = "."
                if more == ";" or more == "":
                    continue
                else:
                    break
            else:
                if not found:
                    print("false.")
                    continue
            print(".")
        except SystemExit:
            break
        except PrologError as e:
            print(f"error: {term_to_str(e.term, quoted=True)}")
        except Exception as e:
            print(f"error: {e}")
    return 0


def cmd_test(args):
    import subprocess
    root = __file__.rsplit("/", 2)[0]
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", f"{root}/tests"])
    return result.returncode


def cmd_viz(args):
    from .viz import run_and_export_trace
    eng = Engine(backend="wam")
    eng.consult_file(args.file)
    out_path = run_and_export_trace(eng, args.goal, args.out)
    print(f"wrote {out_path}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="warren", description="Warren: Prolog on a real WAM")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="consult a file and run a goal")
    p_run.add_argument("file")
    p_run.add_argument("goal", nargs="?", default=None)
    p_run.add_argument("--all", action="store_true", help="print all solutions")
    p_run.add_argument("--backend", choices=["wam", "golden"], default="wam")
    p_run.set_defaults(func=cmd_run)

    p_repl = sub.add_parser("repl", help="interactive top-level")
    p_repl.add_argument("file", nargs="?", default=None)
    p_repl.add_argument("--backend", choices=["wam", "golden"], default="wam")
    p_repl.set_defaults(func=cmd_repl)

    p_test = sub.add_parser("test", help="run the unit test suite")
    p_test.set_defaults(func=cmd_test)

    p_viz = sub.add_parser("viz", help="run a goal and export an HTML WAM execution visualizer")
    p_viz.add_argument("file")
    p_viz.add_argument("goal")
    p_viz.add_argument("--out", default="warren_trace.html")
    p_viz.set_defaults(func=cmd_viz)

    ns = parser.parse_args(argv)
    return ns.func(ns)


if __name__ == "__main__":
    sys.exit(main())
