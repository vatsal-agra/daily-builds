"""The interactive top-level: consult a file, run queries, step through
solutions with ';'/'.' the way a real Prolog top-level does."""

import sys

from .engine import make_engine
from .errors import HaltSignal, HornError
from .parser import parse_term
from .runstack import run_with_stack
from .terms import Var, format_term
from .unify import undo_to


def query_vars(term):
    """Collect the named (non-'_') variables that appear in a query, so
    bindings can be reported by name. Walks the term structure iteratively
    (not recursively) -- a query built from a several-thousand-element list
    literal is a several-thousand-deep chain of './2' compounds, and a
    naive recursive walk would blow the Python stack on exactly the kind of
    query the engine itself (via runstack.py's dedicated big-stack thread)
    is built to handle."""
    seen = set()
    out = []
    stack = [term]  # NOTE: do NOT deref anything here -- we want the
    # *original* query variables, not whatever they ended up bound to.
    while stack:
        t = stack.pop()
        if isinstance(t, Var):
            if t.name != "_" and id(t) not in seen:
                seen.add(id(t))
                out.append(t)
        elif hasattr(t, "args"):
            stack.extend(reversed(t.args))
    return out


def format_solution(vars_):
    if not vars_:
        return "true."
    return ", ".join(f"{v.name} = {format_term(v)}" for v in vars_) + "."


def run_repl(files, occurs_check=False, trace=False, input_stream=None, output=None):
    out = output or sys.stdout
    inp = input_stream or sys.stdin

    def notify(event, key):
        if trace:
            print(f"  [trace] {event}: {key[0]}/{key[1]}", file=out)

    engine = make_engine(occurs_check=occurs_check, notify=notify if trace else None)
    for path in files:
        with open(path, encoding="utf-8") as f:
            engine.consult_text(f.read())
        print(f"consulted {path}", file=out)

    print("Horn REPL. Enter a query ending in '.'; ';' for the next solution, any other line to stop. 'halt.' to quit.", file=out)
    buffer = ""
    while True:
        print("|  " if buffer else "?- ", end="", file=out)
        out.flush()
        try:
            line = inp.readline()
        except (EOFError, KeyboardInterrupt):
            print(file=out)
            return
        if line == "":
            return
        buffer += line
        if "." not in line:
            continue
        text = buffer
        buffer = ""
        text = text.strip()
        if not text:
            continue
        try:
            goal = parse_term(text)
        except HornError as e:
            print(f"error: {e}", file=out)
            continue
        vars_ = query_vars(goal)
        found_any = [False]

        def work():
            for _ in engine.solve_top(goal):
                found_any[0] = True
                print(format_solution(vars_), file=out)
                cont = inp.readline().strip()
                if cont != ";":
                    break

        # See the matching comment in cli.py's _run_query: a query
        # abandoned before its solve() generator is exhausted (stopping
        # early on anything other than ';') never runs its own trail
        # cleanup, so the REPL -- which, unlike the CLI, keeps one Engine
        # alive across many queries in a session -- must undo back to this
        # mark itself or leak a little more of the trail on every query.
        mark = len(engine.trail)
        try:
            run_with_stack(work)
            if not found_any[0]:
                print("false.", file=out)
        except HaltSignal as h:
            print(f"halt({h.code})", file=out)
            return
        except HornError as e:
            print(f"error: {e}", file=out)
        except RecursionError:
            print("error: recursion depth exceeded (query too deep)", file=out)
        finally:
            undo_to(engine.trail, mark)
