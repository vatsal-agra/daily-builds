import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kiln.asm.assembler import assemble
from kiln.wasm.encoder import encode_module
from kiln.wasm.decoder import decode_module
from kiln.wasm.interpreter import Instance
from kiln.pebble.parser import parse as pebble_parse
from kiln.pebble.compiler import compile_program
from kiln import host

NODE = shutil.which("node")
NODE_RUNNER = ROOT / "tools" / "node_runner.js"


def assemble_bytes(kwat_src):
    return encode_module(assemble(kwat_src))


def instantiate(wasm_bytes):
    module = decode_module(wasm_bytes)
    imports, holder = host.default_imports()
    inst = Instance(module, imports)
    holder.append(inst)
    return inst


def run_kwat(kwat_src, func, args):
    inst = instantiate(assemble_bytes(kwat_src))
    return inst.call(func, args)


def compile_pebble(src, entry=None):
    funcs = pebble_parse(src)
    module, func_index = compile_program(funcs, entry)
    return encode_module(module), func_index


def run_pebble(src, func, args):
    wasm_bytes, _ = compile_pebble(src)
    inst = instantiate(wasm_bytes)
    return inst.call(func, args)


def node_available():
    return NODE is not None


RESULT_PREFIX = "KILN_RESULT:"


def extract_node_result(stdout):
    """node_runner.js's structured result always carries this prefix, so
    it can be found even if the module's own stdout output (env.print,
    WASI fd_write) has no trailing newline and ends up glued to it."""
    idx = stdout.rfind(RESULT_PREFIX)
    if idx == -1:
        raise RuntimeError(f"node_runner produced no {RESULT_PREFIX} line: {stdout!r}")
    return json.loads(stdout[idx + len(RESULT_PREFIX):].strip())


def run_in_node(wasm_bytes, func, args, tmp_path):
    wasm_file = tmp_path / "module.wasm"
    wasm_file.write_bytes(wasm_bytes)
    proc = subprocess.run(
        [NODE, str(NODE_RUNNER), str(wasm_file), func] + [str(a) for a in args],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(f"node_runner failed: {proc.stderr}")
    return extract_node_result(proc.stdout)
