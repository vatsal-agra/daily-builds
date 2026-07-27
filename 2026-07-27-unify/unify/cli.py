"""Command-line entry point: `python3 -m unify.cli <command> ...`

Commands:
    check <file>          parse + infer; print the principal type
    run   <file>          parse + infer + evaluate; print the result
    trace <file>          like check, but also print the full derivation tree
    repl                   interactive read-eval-print loop
"""

import sys

from .lexer import LexError
from .parser import parse, ParseError
from .infer import infer_program, InferError
from .evaluator import eval_expr, EvalError, format_value
from .diagnostics import format_error_at, format_error_span
from .types import pretty

# Unify has no tail-call optimization: each level of recursion in a Unify
# program costs several real Python stack frames. The default CPython limit
# (1000) is too low for even modest recursive programs (e.g. summing a list
# of a few hundred elements), so raise it well above default. This is a
# soft counter, not a hardware limit — RecursionError is still caught
# cleanly wherever eval_expr is invoked, below.
sys.setrecursionlimit(max(sys.getrecursionlimit(), 100_000))


def render_judgment(j, indent=0):
    pad = "  " * indent
    note = f"  ({j.note})" if j.note else ""
    lines = [f"{pad}{j.label} : {pretty(j.ty)}{note}"]
    for c in j.children:
        lines.append(render_judgment(c, indent + 1))
    return "\n".join(lines)


def read_source(path):
    """Read `path`. Returns (source, None) or (None, error_message)."""
    try:
        with open(path) as f:
            return f.read(), None
    except OSError as e:
        return None, f"error: cannot read '{path}': {e.strerror or e}"


def parse_or_error(source):
    """Returns (expr, None) or (None, formatted_error)."""
    try:
        return parse(source), None
    except LexError as e:
        return None, format_error_at(source, e.message, e.line, e.col)
    except ParseError as e:
        return None, format_error_at(source, e.message, e.line, e.col)


def infer_or_error(source, expr, base_env=None, start_counter=0):
    """Returns ((type, judgment, next_counter), None) or (None, formatted_error)."""
    try:
        return infer_program(expr, base_env=base_env, start_counter=start_counter), None
    except InferError as e:
        return None, format_error_span(source, e.message, e.span)


def eval_or_error(source, expr, expr_span, env=None):
    """Returns (value, None) or (None, formatted_error)."""
    try:
        return eval_expr(dict(env) if env else {}, expr), None
    except EvalError as e:
        return None, format_error_span(source, e.message, e.span or expr_span)
    except RecursionError:
        return None, (
            "error: recursion too deep (stack overflow)\n"
            "Unify has no tail-call optimization, so deeply recursive "
            "programs are limited by the Python call stack.\n"
        )


def check_source(source, trace=False, base_env=None):
    """Parse + infer `source`. Returns (ok, output_text)."""
    expr, err = parse_or_error(source)
    if err:
        return False, err
    result, err = infer_or_error(source, expr, base_env=base_env)
    if err:
        return False, err
    ty, judgment, _next_counter = result
    out = []
    if trace:
        out.append("--- derivation ---")
        out.append(render_judgment(judgment))
        out.append("")
    out.append(f"type: {pretty(ty)}")
    return True, "\n".join(out)


def run_source(source, trace=False, base_env=None, base_val_env=None):
    """Parse + infer + evaluate `source`. Returns (ok, output_text)."""
    expr, err = parse_or_error(source)
    if err:
        return False, err
    result, err = infer_or_error(source, expr, base_env=base_env)
    if err:
        return False, err
    ty, judgment, _next_counter = result

    out = []
    if trace:
        out.append("--- derivation ---")
        out.append(render_judgment(judgment))
        out.append("")
    out.append(f"type: {pretty(ty)}")

    value, err = eval_or_error(source, expr, expr.span, env=base_val_env)
    if err:
        return False, err
    out.append(f"value: {format_value(value)}")
    return True, "\n".join(out)


def cmd_check(path, trace=False):
    source, err = read_source(path)
    if err:
        print(err)
        return 1
    ok, output = check_source(source, trace=trace)
    print(output)
    return 0 if ok else 1


def cmd_run(path, trace=False):
    source, err = read_source(path)
    if err:
        print(err)
        return 1
    ok, output = run_source(source, trace=trace)
    print(output)
    return 0 if ok else 1


def cmd_repl():
    from .repl import main as repl_main
    repl_main()
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    trace = "--trace" in rest
    rest = [a for a in rest if a != "--trace"]

    if cmd == "check":
        if not rest:
            print("usage: unify check <file> [--trace]")
            return 1
        return cmd_check(rest[0], trace=trace)
    if cmd == "run":
        if not rest:
            print("usage: unify run <file> [--trace]")
            return 1
        return cmd_run(rest[0], trace=trace)
    if cmd == "trace":
        if not rest:
            print("usage: unify trace <file>")
            return 1
        return cmd_check(rest[0], trace=True)
    if cmd == "repl":
        return cmd_repl()

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
