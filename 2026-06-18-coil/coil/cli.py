"""Command-line interface for Coil: run files, REPL, disassemble, AST dump."""

import argparse
import sys

from . import compile_source_text, run_source, stringify
from .errors import CoilError, ParseError
from .lexer import T, tokenize
from .parser import Parser
from .vm import VM


def _looks_like_expression(src):
    """True if `src` is a single expression with no trailing statement syntax."""
    stripped = src.strip()
    if not stripped or stripped.endswith(";") or stripped.endswith("}"):
        return False
    try:
        p = Parser(tokenize(stripped))
        p._expression()
        return p._peek().type == T.EOF
    except CoilError:
        return False


def run_file(path, gc_stress=False, trace_gc=False):
    try:
        with open(path, "r") as f:
            source = f.read()
    except OSError as e:
        sys.stderr.write(f"coil: cannot open {path}: {e}\n")
        return 74
    return _execute(source, path, gc_stress=gc_stress, trace_gc=trace_gc)


def _execute(source, filename, gc_stress=False, trace_gc=False):
    try:
        run_source(source, gc_stress=gc_stress, trace_gc=trace_gc, name=filename)
        return 0
    except CoilError as e:
        sys.stderr.write(e.render(source=source, filename=filename) + "\n")
        # 65 = data/compile error, 70 = runtime error (sysexits-style)
        return 70 if e.kind == "runtime error" else 65


def disassemble_file(path):
    from .disasm import disassemble
    try:
        with open(path, "r") as f:
            source = f.read()
    except OSError as e:
        sys.stderr.write(f"coil: cannot open {path}: {e}\n")
        return 74
    try:
        fn = compile_source_text(source, name=path)
    except CoilError as e:
        sys.stderr.write(e.render(source=source, filename=path) + "\n")
        return 65
    print(disassemble(fn))
    return 0


def dump_ast(path):
    from .parser import parse
    try:
        with open(path, "r") as f:
            source = f.read()
    except OSError as e:
        sys.stderr.write(f"coil: cannot open {path}: {e}\n")
        return 74
    try:
        ast = parse(source)
    except CoilError as e:
        sys.stderr.write(e.render(source=source, filename=path) + "\n")
        return 65
    import pprint
    for node in ast:
        pprint.pprint(node)
    return 0


def repl(gc_stress=False):
    print("Coil REPL — type an expression or statement, Ctrl-D to exit.")
    vm = VM(gc_stress=gc_stress)
    buffer = ""
    while True:
        prompt = "coil> " if not buffer else "  ... "
        try:
            line = input(prompt)
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print("\n(interrupted)")
            buffer = ""
            continue
        buffer = (buffer + "\n" + line) if buffer else line
        if not buffer.strip():
            buffer = ""
            continue
        # echo expression results
        src = buffer
        if _looks_like_expression(buffer):
            src = "print (" + buffer + ");"
        try:
            fn = compile_source_text(src, name="<repl>")
        except ParseError as e:
            # Keep buffering only when input genuinely ran out, i.e. the error
            # sits at the EOF token (an incomplete multi-line construct).
            if _error_at_eof(buffer, e):
                continue  # keep buffer, read more
            sys.stderr.write(e.render(source=buffer, filename="<repl>") + "\n")
            buffer = ""
            continue
        except CoilError as e:
            sys.stderr.write(e.render(source=buffer, filename="<repl>") + "\n")
            buffer = ""
            continue
        buffer = ""
        try:
            vm.interpret(fn)
        except CoilError as e:
            sys.stderr.write(e.render(source=src, filename="<repl>") + "\n")
    return 0


def _error_at_eof(src, error):
    """True if the parse error occurred at the final (EOF) token."""
    toks = tokenize(src)
    eof = toks[-1]
    return error.line == eof.line and error.col == eof.col


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="coil", description="Coil — a bytecode-VM scripting language.")
    parser.add_argument("file", nargs="?", help="a .coil source file to run")
    parser.add_argument("--repl", action="store_true", help="start interactive REPL")
    parser.add_argument("--disasm", action="store_true",
                        help="disassemble the file's bytecode instead of running")
    parser.add_argument("--ast", action="store_true",
                        help="dump the parsed AST instead of running")
    parser.add_argument("--gc-stress", action="store_true",
                        help="run the GC before every allocation")
    parser.add_argument("--trace-gc", action="store_true",
                        help="print a line for each garbage collection")
    args = parser.parse_args(argv)

    if args.repl or args.file is None:
        return repl(gc_stress=args.gc_stress)

    if args.disasm:
        return disassemble_file(args.file)
    if args.ast:
        return dump_ast(args.file)
    return run_file(args.file, gc_stress=args.gc_stress, trace_gc=args.trace_gc)
