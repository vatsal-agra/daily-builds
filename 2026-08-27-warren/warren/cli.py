"""Warren's command-line interface."""
import argparse
import sys
import threading

from .engine import Engine
from .pretty import term_to_str
from .errors import PrologError
from .lexer import LexError
from .parser import ParseError


class CliError(Exception):
    """A clean, user-facing error message (no Python traceback)."""


def cmd_run(args):
    eng = Engine(backend=args.backend)
    _consult_file_or_die(eng, args.file)
    if args.goal:
        return _run_goal(eng, args.goal, all_solutions=args.all)
    return 0


def _consult_file_or_die(eng, path):
    try:
        eng.consult_file(path)
    except FileNotFoundError:
        raise CliError(f"no such file: {path}")
    except (ParseError, LexError) as e:
        raise CliError(f"syntax error in {path}: {e}")


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
    except (ParseError, LexError) as e:
        print(f"warren: syntax error in goal: {e}", file=sys.stderr)
        return 1
    except PrologError as e:
        print(f"warren: unhandled exception: {term_to_str(e.term, quoted=True)}", file=sys.stderr)
        return 1
    except RecursionError:
        print("warren: recursion limit exceeded (very deep term or infinite recursion)", file=sys.stderr)
        return 1
    return 0


def cmd_repl(args):
    eng = Engine(backend=args.backend)
    if args.file:
        _consult_file_or_die(eng, args.file)
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
    _consult_file_or_die(eng, args.file)
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
    return _run_with_big_stack(lambda: _dispatch(ns))


def _dispatch(ns):
    try:
        return ns.func(ns)
    except CliError as e:
        print(f"warren: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


def _run_with_big_stack(fn):
    """Run fn() on a worker thread with a much larger C stack than the
    default (~8MB), so warren.setrecursionlimit's raised Python-level
    limit (see warren/__init__.py) fails as a clean RecursionError on
    pathological input rather than a hard segfault on merely large
    input (e.g. a several-thousand-element list)."""
    result = {}

    def target():
        try:
            result["value"] = fn()
        except BaseException as e:
            result["exc"] = e

    old_stack_size = threading.stack_size()
    try:
        threading.stack_size(512 * 1024 * 1024)
    except (ValueError, RuntimeError):
        pass  # platform doesn't support a custom stack size; proceed with the default
    t = threading.Thread(target=target, daemon=True)
    t.start()
    try:
        t.join()
    except KeyboardInterrupt:
        # Ctrl-C only ever lands on the main thread; let the process
        # exit immediately (the worker is a daemon thread) rather than
        # hanging on a join() that will never see the interrupt.
        print()
        return 130
    try:
        threading.stack_size(old_stack_size)
    except (ValueError, RuntimeError):
        pass
    if "exc" in result:
        raise result["exc"]
    return result.get("value", 0)


if __name__ == "__main__":
    sys.exit(main())
