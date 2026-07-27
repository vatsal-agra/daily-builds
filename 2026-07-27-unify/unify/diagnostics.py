"""Render lex/parse/type/eval errors as source-anchored, human-readable text.

    error: expected int, found bool
      --> line 1, column 15
       |
     1 | let f = fun x -> x + true in f 1
       |               ^^^^^^^^^^

Every error in this project (LexError, ParseError, InferError, EvalError)
carries either a (line, col) pair or a source (start, end) char-offset span,
so the CLI, REPL, and web UI can all share this one renderer.
"""


def _get_line(source, line_no):
    lines = source.split("\n")
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return ""


def format_error_at(source, message, line, col, length=1):
    src_line = _get_line(source, line)
    length = max(1, min(length, max(1, len(src_line) - (col - 1))))
    caret_line = " " * (col - 1) + "^" * length
    gutter = f"{line}"
    pad = " " * len(gutter)
    return (
        f"error: {message}\n"
        f"  --> line {line}, column {col}\n"
        f"{pad} |\n"
        f"{gutter} | {src_line}\n"
        f"{pad} | {caret_line}\n"
    )


def format_error_span(source, message, span):
    start, end = span
    line = source.count("\n", 0, start) + 1
    last_nl = source.rfind("\n", 0, start)
    col = start - last_nl
    length = max(1, end - start)
    return format_error_at(source, message, line, col, length)
