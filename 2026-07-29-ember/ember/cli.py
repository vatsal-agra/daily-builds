"""Command-line entry point for Ember.

Every subcommand catches Ember's own error types (lex/parse/runtime) and
prints a clean one-line `error: ...` message with exit code 1 -- no raw
Python tracebacks for ordinary user mistakes (missing file, wrong
argument count, bad syntax, division by zero, etc).
"""

import argparse
import sys

from .lexer import LexError
from .parser import parse, ParseError
from .interpreter import Interpreter
from .codegen_x64 import compile_program
from .errors import EmberRuntimeError
from .disasm import format_listing, objdump_available
from .transpile_c import run_via_gcc, gcc_available
from .ast_print import format_program, format_fn
from .bench import benchmark
from .optimize import fold_constants


class CliError(Exception):
    pass


def _load_program(path):
    try:
        with open(path) as f:
            source = f.read()
    except OSError as e:
        raise CliError(f"cannot read {path!r}: {e.strerror}")
    try:
        return parse(source)
    except (LexError, ParseError) as e:
        raise CliError(f"{path}: {e}")


def _parse_args(raw_args):
    out = []
    for a in raw_args:
        try:
            out.append(int(a))
        except ValueError:
            raise CliError(f"argument {a!r} is not an integer")
    return out


def _find_fn(program, name):
    for fn in program.functions:
        if fn.name == name:
            return fn
    available = ", ".join(f.name for f in program.functions) or "(none)"
    raise CliError(f"no function named {name!r}; defined: {available}")


def cmd_run(args):
    program = _load_program(args.file)
    _find_fn(program, args.fn)
    argv = _parse_args(args.args)
    if args.opt:
        program = fold_constants(program)
    compiled = compile_program(program)
    print(compiled.call(args.fn, argv))


def cmd_interp(args):
    program = _load_program(args.file)
    _find_fn(program, args.fn)
    argv = _parse_args(args.args)
    print(Interpreter(program).call(args.fn, argv))


def cmd_compare(args):
    program = _load_program(args.file)
    _find_fn(program, args.fn)
    argv = _parse_args(args.args)

    jit_program = fold_constants(program) if args.opt else program
    interp_result = Interpreter(program).call(args.fn, argv)
    jit_result = compile_program(jit_program).call(args.fn, argv)
    print(f"interpreter: {interp_result}")
    print(f"jit:         {jit_result}" + ("  (constant-folded)" if args.opt else ""))

    ok = interp_result == jit_result
    if gcc_available():
        gcc_result = run_via_gcc(jit_program, args.fn, argv)
        print(f"gcc:         {gcc_result}")
        ok = ok and interp_result == gcc_result
    else:
        print("gcc:         (gcc not available on this system, skipped)")

    print("MATCH" if ok else "MISMATCH")
    if not ok:
        sys.exit(1)


def cmd_ast(args):
    program = _load_program(args.file)
    if args.fn:
        fn = _find_fn(program, args.fn)
        print(format_fn(fn))
    else:
        print(format_program(program), end="")


def cmd_disasm(args):
    program = _load_program(args.file)
    compiled = compile_program(program)
    if args.fn:
        _find_fn(program, args.fn)
        if args.fn not in compiled.entry_offsets:
            raise CliError(f"no function named {args.fn!r}")
        offsets = sorted(compiled.entry_offsets.values()) + [len(compiled.code_bytes)]
        start = compiled.entry_offsets[args.fn]
        end = min(o for o in offsets if o > start) if any(o > start for o in offsets) else len(compiled.code_bytes)
        code = compiled.code_bytes[start:end]
    else:
        code = compiled.code_bytes
    if not objdump_available():
        raise CliError("objdump is not available on this system")
    print(format_listing(code))


def cmd_bench(args):
    program = _load_program(args.file)
    _find_fn(program, args.fn)
    argv = _parse_args(args.args)
    stats = benchmark(program, args.fn, argv, optimize=args.opt)
    i, j = stats["interpreter"], stats["jit"]
    print(f"{args.fn}({', '.join(map(str, argv))}) = {stats['result']}")
    print(f"interpreter: {i['iters']} calls in {i['elapsed']:.4f}s "
          f"({i['per_call']*1e6:.2f} us/call)")
    print(f"jit:         {j['iters']} calls in {j['elapsed']:.4f}s "
          f"({j['per_call']*1e6:.2f} us/call)")
    print(f"speedup:     {stats['speedup']:.1f}x")


def cmd_viz(args):
    from .report import generate_report
    program = _load_program(args.file)
    bench_program = fold_constants(program) if args.opt else None
    html = generate_report(args.file, program, bench_fn=args.bench_fn,
                            bench_args=_parse_args(args.bench_args or []),
                            bench_program=bench_program)
    with open(args.out, "w") as f:
        f.write(html)
    print(f"wrote {args.out}")


def cmd_demo(args):
    from . import demo
    demo.run()


def build_parser():
    p = argparse.ArgumentParser(prog="ember", description="A from-scratch JIT compiler to real x86-64 machine code.")
    sub = p.add_subparsers(dest="command", required=True)

    def add_fn_args(sp):
        sp.add_argument("file")
        sp.add_argument("fn")
        sp.add_argument("args", nargs="*")

    sp = sub.add_parser("run", help="JIT-compile and execute a function")
    add_fn_args(sp)
    sp.add_argument("--opt", action="store_true", help="apply constant folding before compiling")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("interp", help="Run a function through the reference interpreter")
    add_fn_args(sp)
    sp.set_defaults(func=cmd_interp)

    sp = sub.add_parser("compare", help="Run interpreter vs JIT vs gcc and report any mismatch")
    add_fn_args(sp)
    sp.add_argument("--opt", action="store_true", help="apply constant folding to the JIT/gcc side before compiling")
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("ast", help="Print the AST")
    sp.add_argument("file")
    sp.add_argument("--fn", default=None)
    sp.set_defaults(func=cmd_ast)

    sp = sub.add_parser("disasm", help="Disassemble the JIT-compiled machine code via objdump")
    sp.add_argument("file")
    sp.add_argument("--fn", default=None)
    sp.set_defaults(func=cmd_disasm)

    sp = sub.add_parser("bench", help="Measure interpreter vs JIT wall-clock speed")
    add_fn_args(sp)
    sp.add_argument("--opt", action="store_true", help="constant-fold before compiling the JIT side")
    sp.set_defaults(func=cmd_bench)

    sp = sub.add_parser("viz", help="Generate the interactive HTML report")
    sp.add_argument("file")
    sp.add_argument("--out", default="report.html")
    sp.add_argument("--bench-fn", default=None)
    sp.add_argument("--bench-args", nargs="*", default=None)
    sp.add_argument("--opt", action="store_true", help="constant-fold before compiling the benchmarked JIT")
    sp.set_defaults(func=cmd_viz)

    sp = sub.add_parser("demo", help="Run the full end-to-end feature showcase")
    sp.set_defaults(func=cmd_demo)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except EmberRuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
