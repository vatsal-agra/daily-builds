"""Kiln command-line interface.

  kiln assemble in.kwat -o out.wasm
  kiln run out.wasm funcname arg1 arg2 ...
  kiln compile in.pebble -o out.wasm [--entry main]
  kiln disasm out.wasm
  kiln verify out.wasm funcname arg1 arg2 ...        (cross-check vs Node)
  kiln trace out.wasm funcname arg1 arg2 ... --html -o trace.html
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .asm.assembler import assemble, AssembleError
from .wasm.decoder import decode_module
from .wasm.encoder import encode_module
from .wasm.interpreter import Instance, WasmTrap
from .wasm.types import I32, I64, F32, F64
from .pebble.parser import parse as pebble_parse, PebbleSyntaxError
from .pebble.compiler import compile_program, PebbleCompileError
from .disasm import disassemble
from .trace import trace_call
from . import host

ROOT_DIR = Path(__file__).resolve().parent.parent
NODE_RUNNER = ROOT_DIR / "tools" / "node_runner.js"
VIZ_TEMPLATE = ROOT_DIR / "viz" / "template.html"
RESULT_PREFIX = "KILN_RESULT:"


class CliError(Exception):
    """A clean, user-facing CLI failure (as opposed to a bug)."""


def _parse_arg(text, valtype):
    try:
        if valtype in (I32,):
            return int(text, 0) & 0xFFFFFFFF
        if valtype in (I64,):
            return int(text, 0) & 0xFFFFFFFFFFFFFFFF
        return float(text)
    except ValueError:
        raise CliError(f"can't parse {text!r} as a numeric argument")


def _read_file(path, mode="r"):
    try:
        with open(path, mode) as fh:
            return fh.read()
    except OSError as e:
        raise CliError(f"can't read {path}: {e.strerror}")


def _load_instance(wasm_path):
    data = _read_file(wasm_path, "rb")
    module = decode_module(data)
    imports, holder = host.default_imports()
    inst = Instance(module, imports)
    holder.append(inst)
    return inst


def cmd_assemble(args):
    src = _read_file(args.input)
    module = assemble(src)
    data = encode_module(module)
    with open(args.output, "wb") as fh:
        fh.write(data)
    print(f"wrote {args.output} ({len(data)} bytes)")
    return 0


def cmd_compile(args):
    src = _read_file(args.input)
    funcs = pebble_parse(src)
    module, func_index = compile_program(funcs, args.entry)
    data = encode_module(module)
    with open(args.output, "wb") as fh:
        fh.write(data)
    print(f"wrote {args.output} ({len(data)} bytes); functions: {', '.join(func_index)}")
    return 0


def _resolve_export_call(inst, export_name, raw_args):
    try:
        fidx = inst.export_index(export_name)
    except KeyError:
        available = [e.name for e in inst.module.exports if e.kind == "func"]
        raise CliError(f"no exported function {export_name!r} (available: {', '.join(available) or 'none'})")
    ftype = inst.module.types[inst.module.func_type_index(fidx)]
    if len(raw_args) != len(ftype.params):
        raise CliError(f"{export_name} expects {len(ftype.params)} args, got {len(raw_args)}")
    return [_parse_arg(a, t) for a, t in zip(raw_args, ftype.params)]


def cmd_run(args):
    inst = _load_instance(args.wasm)
    call_args = _resolve_export_call(inst, args.export_name, args.args)
    results = inst.call(args.export_name, call_args)
    print(" ".join(str(r) for r in results) if results else "(no results)")
    return 0


def cmd_disasm(args):
    module = decode_module(_read_file(args.wasm, "rb"))
    print(disassemble(module))
    return 0


def cmd_verify(args):
    """Cross-checks a call against Node's real WebAssembly engine — the
    same differential-testing oracle the test suite uses, exposed as a
    standalone CLI command."""
    node = shutil.which("node")
    if node is None:
        raise CliError("verify requires `node` on PATH (not found)")
    if not NODE_RUNNER.exists():
        raise CliError(f"missing verification harness: {NODE_RUNNER}")

    inst = _load_instance(args.wasm)
    call_args = _resolve_export_call(inst, args.export_name, args.args)
    try:
        kiln_results = inst.call(args.export_name, call_args)
        kiln_outcome = ("ok", kiln_results)
    except WasmTrap as e:
        kiln_outcome = ("trap", str(e))

    proc = subprocess.run(
        [node, str(NODE_RUNNER), args.wasm, args.export_name] + [str(a) for a in call_args],
        capture_output=True, text=True, timeout=30,
    )
    idx = proc.stdout.rfind(RESULT_PREFIX)
    if idx == -1:
        raise CliError(f"node_runner produced no result line (stderr: {proc.stderr.strip()})")
    node_json = json.loads(proc.stdout[idx + len(RESULT_PREFIX):].strip())
    node_outcome = ("trap", node_json["trap"]) if "trap" in node_json else ("ok", node_json.get("results", []))

    print(f"kiln : {kiln_outcome[0]:5s} {kiln_outcome[1]}")
    print(f"node : {node_outcome[0]:5s} {node_outcome[1]}")
    if kiln_outcome[0] != node_outcome[0]:
        print("MISMATCH: one engine trapped, the other didn't", file=sys.stderr)
        return 1
    if kiln_outcome[0] == "ok":
        kiln_vals = [float(v) if isinstance(v, float) else v for v in kiln_outcome[1]]
        node_vals = node_outcome[1]
        matches = len(kiln_vals) == len(node_vals) and all(
            (float(kv) == float(nv)) if isinstance(kv, float) else (_values_equal_mod_sign(kv, nv))
            for kv, nv in zip(kiln_vals, node_vals)
        )
        if not matches:
            print(f"MISMATCH: {kiln_vals} != {node_vals}", file=sys.stderr)
            return 1
    print("MATCH")
    return 0


def _values_equal_mod_sign(kiln_value, node_value):
    nv = int(node_value)
    if nv < 0:
        nv += 1 << 32 if -nv <= (1 << 32) else 1 << 64
    return int(kiln_value) == nv


def cmd_trace(args):
    inst = _load_instance(args.wasm)
    call_args = _resolve_export_call(inst, args.export_name, args.args)
    result = trace_call(inst, args.export_name, call_args, max_steps=args.max_steps)
    payload = {
        "title": f"{args.export_name}({', '.join(str(a) for a in call_args)})",
        "export": args.export_name,
        "args": call_args,
        **result,
    }
    if args.html:
        if not VIZ_TEMPLATE.exists():
            raise CliError(f"missing visualizer template: {VIZ_TEMPLATE}")
        template = VIZ_TEMPLATE.read_text()
        html = template.replace("__TRACE_JSON__", json.dumps(payload))
        Path(args.output).write_text(html)
        print(f"wrote {args.output} ({len(result['steps'])} steps, open it in a browser)")
    else:
        Path(args.output).write_text(json.dumps(payload, indent=2))
        print(f"wrote {args.output} ({len(result['steps'])} steps)")
    if result["truncated"]:
        print(f"note: trace truncated at {args.max_steps} steps", file=sys.stderr)
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

    pv = sub.add_parser("verify", help="cross-check a call against Node's real WebAssembly engine")
    pv.add_argument("wasm")
    pv.add_argument("export_name")
    pv.add_argument("args", nargs="*")
    pv.set_defaults(func=cmd_verify)

    pt = sub.add_parser("trace", help="record a step-by-step execution trace (JSON or standalone HTML viewer)")
    pt.add_argument("wasm")
    pt.add_argument("export_name")
    pt.add_argument("args", nargs="*")
    pt.add_argument("-o", "--output", required=True)
    pt.add_argument("--html", action="store_true", help="emit a standalone interactive HTML viewer instead of raw JSON")
    pt.add_argument("--max-steps", type=int, default=4000)
    pt.set_defaults(func=cmd_trace)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as e:
        print(f"kiln {args.command}: {e}", file=sys.stderr)
        return 1
    except (AssembleError, PebbleSyntaxError, PebbleCompileError, SyntaxError) as e:
        print(f"kiln {args.command}: {e}", file=sys.stderr)
        return 1
    except WasmTrap as e:
        print(f"trap: {e}", file=sys.stderr)
        return 1
    except KeyError as e:
        print(f"kiln {args.command}: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"kiln {args.command}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
