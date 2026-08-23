#!/usr/bin/env python3
"""
Runic CLI.

  cli.py compile prog.rn -o prog.wasm
  cli.py run prog.rn funcname arg1 arg2 ...
  cli.py disasm prog.rn|prog.wasm
  cli.py trace prog.rn funcname arg1 arg2 ... -o trace.html
  cli.py verify
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compiler.frontend import compile_source, CompileError
from compiler.interpreter import Instance, WasmTrap, decode_module
from compiler.disasm import disassemble
from compiler.viz import generate_html


def _load_wasm_bytes(path):
    if path.endswith(".wasm"):
        with open(path, "rb") as f:
            return f.read()
    with open(path) as f:
        src = f.read()
    try:
        return compile_source(src).wasm_bytes
    except CompileError as e:
        print(f"compile error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_compile(args):
    with open(args.source) as f:
        src = f.read()
    try:
        result = compile_source(src)
    except CompileError as e:
        print(f"compile error: {e}", file=sys.stderr)
        sys.exit(1)
    out = args.output or (os.path.splitext(args.source)[0] + ".wasm")
    with open(out, "wb") as f:
        f.write(result.wasm_bytes)
    funcs = ", ".join(info.name for info in result.checked.func_order)
    print(f"compiled {args.source} -> {out} ({len(result.wasm_bytes)} bytes)")
    print(f"exported functions: {funcs}")


def cmd_run(args):
    wasm_bytes = _load_wasm_bytes(args.source)
    parsed_args = [int(a) for a in args.args]
    inst = Instance(wasm_bytes)
    try:
        result = inst.call_by_name(args.func, parsed_args)
    except WasmTrap as e:
        print(f"trap: {e}")
        sys.exit(1)
    print(result)


def cmd_disasm(args):
    wasm_bytes = _load_wasm_bytes(args.source)
    print(disassemble(wasm_bytes))


def cmd_trace(args):
    mem_hint = None
    if args.source.endswith(".rn"):
        with open(args.source) as f:
            src = f.read()
        try:
            compiled = compile_source(src)
        except CompileError as e:
            print(f"compile error: {e}", file=sys.stderr)
            sys.exit(1)
        wasm_bytes = compiled.wasm_bytes
        mem_hint = compiled.checked.total_mem_bytes
    else:
        wasm_bytes = _load_wasm_bytes(args.source)
    parsed_args = [int(a) for a in args.args]
    html = generate_html(wasm_bytes, args.func, parsed_args, mem_hint_bytes=mem_hint)
    out = args.output or "trace.html"
    with open(out, "w") as f:
        f.write(html)
    print(f"wrote {out}")


def cmd_verify(_args):
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import verify as verify_mod
    sys.exit(verify_mod.main())


def main():
    p = argparse.ArgumentParser(prog="runic", description="Runic WebAssembly toolchain CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("compile", help="compile a .rn file to .wasm")
    pc.add_argument("source")
    pc.add_argument("-o", "--output")
    pc.set_defaults(handler=cmd_compile)

    pr = sub.add_parser("run", help="compile+run a function via the from-scratch interpreter")
    pr.add_argument("source")
    pr.add_argument("func")
    pr.add_argument("args", nargs="*")
    pr.set_defaults(handler=cmd_run)

    pd = sub.add_parser("disasm", help="disassemble a .rn or .wasm file to WAT-like text")
    pd.add_argument("source")
    pd.set_defaults(handler=cmd_disasm)

    pt = sub.add_parser("trace", help="generate an interactive HTML step-through debugger")
    pt.add_argument("source")
    pt.add_argument("func")
    pt.add_argument("args", nargs="*")
    pt.add_argument("-o", "--output")
    pt.set_defaults(handler=cmd_trace)

    pv = sub.add_parser("verify", help="run the dual-oracle differential verifier over the demo corpus")
    pv.set_defaults(handler=cmd_verify)

    args = p.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
