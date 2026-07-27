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
from .infer import infer_program, InferError, Judgment
from .evaluator import eval_expr, EvalError, format_value
from .diagnostics import format_error_at, format_error_span
from .types import pretty


def render_judgment(j, indent=0):
    pad = "  " * indent
    note = f"  ({j.note})" if j.note else ""
    lines = [f"{pad}{j.label} : {pretty(j.ty)}{note}"]
    for c in j.children:
        lines.append(render_judgment(c, indent + 1))
    return "\n".join(lines)


def run_source(source, filename="<input>", trace=False, base_env=None, base_val_env=None):
    """Parse + infer + evaluate `source`. Returns (ok: bool, output: str)."""
    try:
        expr = parse(source)
    except LexError as e:
        return False, format_error_at(source, e.message, e.line, e.col)
    except ParseError as e:
        return False, format_error_at(source, e.message, e.line, e.col)

    try:
        ty, judgment = infer_program(expr, base_env=base_env)
    except InferError as e:
        return False, format_error_span(source, e.message, e.span)

    out = []
    if trace:
        out.append("--- derivation ---")
        out.append(render_judgment(judgment))
        out.append("")
    out.append(f"type: {pretty(ty)}")

    try:
        value = eval_expr(dict(base_val_env) if base_val_env else {}, expr)
    except EvalError as e:
        span = e.span if e.span else expr.span
        return False, format_error_span(source, e.message, span)

    out.append(f"value: {format_value(value)}")
    return True, "\n".join(out)


def cmd_check(path, trace=False):
    with open(path) as f:
        source = f.read()
    try:
        expr = parse(source)
    except (LexError, ParseError) as e:
        print(format_error_at(source, e.message, e.line, e.col), end="")
        return 1
    try:
        ty, judgment = infer_program(expr)
    except InferError as e:
        print(format_error_span(source, e.message, e.span), end="")
        return 1
    if trace:
        print("--- derivation ---")
        print(render_judgment(judgment))
        print()
    print(f"type: {pretty(ty)}")
    return 0


def cmd_run(path, trace=False):
    with open(path) as f:
        source = f.read()
    ok, output = run_source(source, filename=path, trace=trace)
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
