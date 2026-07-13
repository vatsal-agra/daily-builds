"""Kiln command-line interface.

  kiln assemble in.kwat -o out.wasm
  kiln run out.wasm funcname arg1 arg2 ...
  kiln compile in.pebble -o out.wasm [--entry main]
  kiln disasm out.wasm
  kiln verify out.wasm funcname arg1 arg2 ...   (cross-check vs Node)
"""

import argparse
import sys

from .asm.assembler import assemble, AssembleError
from .wasm.decoder import decode_module
from .wasm.encoder import encode_module
from .wasm.interpreter import Instance, WasmTrap
from .wasm.types import I32, I64, F32, F64
from .pebble.parser import parse as pebble_parse, PebbleSyntaxError
from .pebble.compiler import compile_program, PebbleCompileError
from .disasm import disassemble
from . import host


def _parse_arg(text, valtype):
    if valtype in (I32,):
        return int(text, 0) & 0xFFFFFFFF
    if valtype in (I64,):
        return int(text, 0) & 0xFFFFFFFFFFFFFFFF
    return float(text)


def _load_instance(wasm_path):
    with open(wasm_path, "rb") as fh:
        data = fh.read()
    module = decode_module(data)
    imports, holder = host.default_imports()
    inst = Instance(module, imports)
    holder.append(inst)
    return inst


def cmd_assemble(args):
    with open(args.input) as fh:
        src = fh.read()
    try:
        module = assemble(src)
    except AssembleError as e:
        print(f"kiln assemble: {e}", file=sys.stderr)
        return 1
    data = encode_module(module)
    with open(args.output, "wb") as fh:
        fh.write(data)
    print(f"wrote {args.output} ({len(data)} bytes)")
    return 0


def cmd_compile(args):
    with open(args.input) as fh:
        src = fh.read()
    try:
        funcs = pebble_parse(src)
        module, func_index = compile_program(funcs, args.entry)
    except (PebbleSyntaxError, PebbleCompileError) as e:
        print(f"kiln compile: {e}", file=sys.stderr)
        return 1
    data = encode_module(module)
    with open(args.output, "wb") as fh:
        fh.write(data)
    print(f"wrote {args.output} ({len(data)} bytes); functions: {', '.join(func_index)}")
    return 0


def cmd_run(args):
    inst = _load_instance(args.wasm)
    fidx = inst.export_index(args.export_name)
    ftype = inst.module.types[inst.module.func_type_index(fidx)]
    if len(args.args) != len(ftype.params):
        print(f"kiln run: {args.export_name} expects {len(ftype.params)} args, got {len(args.args)}", file=sys.stderr)
        return 1
    call_args = [_parse_arg(a, t) for a, t in zip(args.args, ftype.params)]
    try:
        results = inst.call(args.export_name, call_args)
    except WasmTrap as e:
        print(f"trap: {e}", file=sys.stderr)
        return 1
    print(" ".join(str(r) for r in results) if results else "(no results)")
    return 0


def cmd_disasm(args):
    with open(args.wasm, "rb") as fh:
        module = decode_module(fh.read())
    print(disassemble(module))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="kiln")
    sub = p.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("assemble", help="assemble a .kwat text file into a .wasm binary")
    pa.add_argument("input")
    pa.add_argument("-o", "--output", required=True)
    pa.set_defaults(func=cmd_assemble)

    pc = sub.add_parser("compile", help="compile a Pebble source file into a .wasm binary")
    pc.add_argument("input")
    pc.add_argument("-o", "--output", required=True)
    pc.add_argument("--entry", default=None)
    pc.set_defaults(func=cmd_compile)

    pr = sub.add_parser("run", help="run an exported function from a .wasm module")
    pr.add_argument("wasm")
    pr.add_argument("export_name")
    pr.add_argument("args", nargs="*")
    pr.set_defaults(func=cmd_run)

    pd = sub.add_parser("disasm", help="disassemble a .wasm module to readable text")
    pd.add_argument("wasm")
    pd.set_defaults(func=cmd_disasm)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
