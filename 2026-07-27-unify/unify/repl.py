"""An interactive read-eval-print loop with persistent `let`-bindings.

Each line is either a bare expression (evaluated once, not persisted) or a
top-level `let [rec] name [params] = expr` (persisted into the session's
type and value environments for every later line to use -- including
polymorphically, since each binding is fully generalized before being
stored). A small prelude (`map`/`filter`/`foldl`/...), written in Unify
itself, loads the same way at startup.

The one subtlety worth knowing if you're reading this file: every
inference call threads a single, session-wide fresh-variable counter
(`state.counter`) through `start_counter`/`next_counter`. Skipping that
and letting each call restart at 0 is exactly the bug documented in
REVIEW.md #7 -- a freshly-minted variable can then numerically collide
with a bound-variable label inside an already-persisted scheme, and
`instantiate()` builds a self-referential substitution that hangs the
process. Every call below passes `start_counter=state.counter` and saves
the returned counter back, without exception.
"""

import sys

from .lexer import tokenize, LexError
from .parser import parse, parse_toplevel, ParseError
from .infer import infer_program, infer_toplevel, InferError
from .evaluator import eval_expr, eval_binding, EvalError, format_value
from .diagnostics import format_error_at, format_error_span
from .types import pretty
from .prelude import PRELUDE

# See the matching comment in cli.py: Unify has no tail-call optimization,
# so the default CPython recursion limit is too low even for modest
# recursive programs. Set here too so `python3 -m unify.repl` alone (not
# just `unify.cli repl`) gets the same protection.
sys.setrecursionlimit(max(sys.getrecursionlimit(), 100_000))

BANNER = "Unify REPL -- a Hindley-Milner language. :help for commands, :quit to exit."

HELP_TEXT = """\
  <expr>                  evaluate an expression (not persisted)
  let [rec] f x .. = expr  define a name, persisted for later lines
  :type <expr>            show an expression's inferred type without running it
  :env                    list every persisted binding and its type
  :help                   show this message
  :quit                   exit
"""


class ReplState:
    def __init__(self):
        self.type_env = {}
        self.value_env = {}
        self.counter = 0


def load_prelude(state, echo=False):
    loaded = []
    for name, source in PRELUDE:
        ok, message = process_statement(state, source)
        if not ok:
            # A prelude bug is our bug, not the user's -- fail loudly.
            raise RuntimeError(f"prelude entry '{name}' failed to load:\n{message}")
        loaded.append(name)
        if echo:
            print(message)
    return loaded


def is_blank(line):
    """True for whitespace-only input AND comment-only input (`# ...`) --
    both should be silently ignored by the REPL loop, not reported as a
    confusing "unexpected token 'EOF'" parse error."""
    try:
        tokens = tokenize(line)
    except LexError:
        return False  # let the real parse below produce the proper error
    return len(tokens) == 1 and tokens[0].kind == "EOF"


def process_statement(state, line):
    """Run one line of input against `state`, mutating it on success.

    Returns (ok, message) -- `message` is either the printable result line
    or a formatted error, exactly like the rest of the CLI's diagnostics.
    """
    try:
        kind, *rest = parse_toplevel(line)
    except LexError as e:
        return False, format_error_at(line, e.message, e.line, e.col)
    except ParseError as e:
        return False, format_error_at(line, e.message, e.line, e.col)

    if kind == "let":
        is_rec, name, value_expr = rest
        try:
            scheme, _judgment, next_counter = infer_toplevel(
                name, value_expr, is_rec, base_env=state.type_env, start_counter=state.counter
            )
        except InferError as e:
            return False, format_error_span(line, e.message, e.span)
        try:
            value = eval_binding(state.value_env, name, value_expr, is_rec)
        except EvalError as e:
            return False, format_error_span(line, e.message, e.span or value_expr.span)
        except RecursionError:
            return False, "error: recursion too deep (stack overflow)"
        state.counter = next_counter
        state.type_env[name] = scheme
        state.value_env[name] = value
        return True, f"{name} : {pretty(scheme.ty)} = {format_value(value)}"

    # kind == "expr"
    (expr,) = rest
    try:
        ty, _judgment, next_counter = infer_program(
            expr, base_env=state.type_env, start_counter=state.counter
        )
    except InferError as e:
        return False, format_error_span(line, e.message, e.span)
    try:
        value = eval_expr(dict(state.value_env), expr)
    except EvalError as e:
        return False, format_error_span(line, e.message, e.span or expr.span)
    except RecursionError:
        return False, "error: recursion too deep (stack overflow)"
    state.counter = next_counter
    return True, f"- : {pretty(ty)} = {format_value(value)}"


def handle_type_query(state, expr_source):
    try:
        expr = parse(expr_source)
    except (LexError, ParseError) as e:
        return format_error_at(expr_source, e.message, e.line, e.col)
    try:
        ty, _judgment, next_counter = infer_program(
            expr, base_env=state.type_env, start_counter=state.counter
        )
    except InferError as e:
        return format_error_span(expr_source, e.message, e.span)
    state.counter = next_counter
    return f"{expr_source} : {pretty(ty)}"


def main():
    state = ReplState()
    print(BANNER)
    load_prelude(state)
    print(f"(loaded prelude: {', '.join(name for name, _ in PRELUDE)})")

    while True:
        try:
            line = input("unify> ")
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            continue

        line = line.strip()
        if not line or is_blank(line):
            continue
        if line in (":quit", ":q", ":exit"):
            break
        if line == ":help":
            print(HELP_TEXT, end="")
            continue
        if line == ":env":
            if not state.type_env:
                print("(empty)")
            for name, scheme in state.type_env.items():
                print(f"{name} : {pretty(scheme.ty)}")
            continue
        if line.startswith(":type "):
            print(handle_type_query(state, line[len(":type "):].strip()))
            continue
        if line.startswith(":"):
            print(f"unknown command {line.split()[0]!r} -- try :help")
            continue

        ok, message = process_statement(state, line)
        print(message)


if __name__ == "__main__":
    sys.exit(main())
