#!/usr/bin/env python3
"""
verify.py — the dual-oracle differential verifier.

For each program in the corpus below: compile it with this project's own
from-scratch encoder, then run every listed call through TWO independent
executors —

  1. compiler/interpreter.py  — our own hand-written WASM decoder + stack
     machine, zero dependency on any WASM runtime.
  2. oracle.mjs                — Node's *native* V8 WebAssembly engine,
     loading the exact same bytes.

— and assert they agree exactly, including on which calls *trap* (divide
by zero, INT_MIN/-1 overflow). Any mismatch is a real bug: either the
encoder produced bytes that mean something different than we intended, or
our interpreter misreads the format it itself only half-independently
implements. Agreement across a real, external, from-someone-else's-code
implementation is a much stronger correctness signal than "our compiler
and our interpreter agree with each other."
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compiler.frontend import compile_source, CompileError
from compiler.interpreter import Instance, WasmTrap

HERE = os.path.dirname(os.path.abspath(__file__))
ORACLE = os.path.join(HERE, "oracle.mjs")
DEMO_DIR = os.path.join(HERE, "demo")

# name -> (calls, read_memory_bytes)
CORPUS = {
    "fib.rn": ([
        {"func": "fib", "args": [0]},
        {"func": "fib", "args": [1]},
        {"func": "fib", "args": [10]},
        {"func": "fib", "args": [20]},
    ], 0),
    "factorial.rn": ([
        {"func": "factorial", "args": [0]},
        {"func": "factorial", "args": [1]},
        {"func": "factorial", "args": [10]},
        {"func": "factorial", "args": [12]},
    ], 0),
    "gcd.rn": ([
        {"func": "gcd", "args": [48, 18]},
        {"func": "gcd", "args": [17, 5]},
        {"func": "gcd", "args": [0, 7]},
        {"func": "gcd", "args": [1071, 462]},
    ], 0),
    "is_prime.rn": ([
        {"func": "is_prime", "args": [n]} for n in [0, 1, 2, 3, 4, 17, 18, 97, 100, 9973]
    ], 0),
    "power.rn": ([
        {"func": "power", "args": [2, 10]},
        {"func": "power", "args": [3, 0]},
        {"func": "power", "args": [5, 5]},
        {"func": "power", "args": [-2, 3]},
    ], 0),
    "logic.rn": ([
        {"func": "check", "args": [1, 1]},
        {"func": "check", "args": [1, -1]},
        {"func": "check", "args": [-1, -1]},
        {"func": "not_test", "args": [0]},
        {"func": "not_test", "args": [5]},
    ], 0),
    "sieve.rn": ([
        {"func": "sieve", "args": [64]},
        {"func": "is_comp", "args": [2]},
        {"func": "is_comp", "args": [4]},
        {"func": "is_comp", "args": [17]},
        {"func": "is_comp", "args": [49]},
    ], 64 * 4),
    "bubble_sort.rn": ([
        {"func": "sort", "args": [10]},
        {"func": "get", "args": [0]},
        {"func": "get", "args": [9]},
        {"func": "get", "args": [5]},
    ], 10 * 4),
    "divmod_edge.rn": ([
        {"func": "div", "args": [7, 2]},
        {"func": "div", "args": [-7, 2]},
        {"func": "div", "args": [7, -2]},
        {"func": "div", "args": [-7, -2]},
        {"func": "rem", "args": [7, 2]},
        {"func": "rem", "args": [-7, 2]},
        {"func": "rem", "args": [7, -2]},
        {"func": "rem", "args": [-7, -2]},
        {"func": "div", "args": [-2147483648, -1]},  # traps: overflow
        {"func": "rem", "args": [-2147483648, -1]},  # does NOT trap, = 0
        {"func": "div", "args": [5, 0]},  # traps: divide by zero
        {"func": "rem", "args": [5, 0]},  # traps: divide by zero
    ], 0),
    # Regression: an unsigned-looking literal must encode to the same bits
    # as its signed equivalent (caught by this exact check during Phase 3).
    "literal_wraparound.rn": ([
        {"func": "big", "args": []},
        {"func": "neg_one", "args": []},
        {"func": "max_i32", "args": []},
    ], 0),
    # Memory is page-granular: in-page-but-past-the-array reads are legal
    # (zero), genuinely out-of-page reads trap — check both.
    "memory_bounds.rn": ([
        {"func": "read_at", "args": [0]},
        {"func": "read_at", "args": [3]},
        {"func": "read_at", "args": [10000]},   # in-page, past the array: legal, reads 0
        {"func": "read_at", "args": [100000]},  # past the whole page: traps
    ], 16),
}


def run_node_oracle(wasm_path, calls, read_memory_bytes):
    plan = {"calls": calls, "readMemoryBytes": read_memory_bytes}
    proc = subprocess.run(
        ["node", ORACLE, wasm_path],
        input=json.dumps(plan),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"node oracle process failed: {proc.stderr}")
    return json.loads(proc.stdout)


def verify_file(rn_path, calls, read_memory_bytes, tmpdir):
    name = os.path.basename(rn_path)
    detail = {"name": name, "passed": True, "lines": []}

    with open(rn_path) as f:
        src = f.read()

    try:
        compiled = compile_source(src)
    except CompileError as e:
        detail["passed"] = False
        detail["lines"].append(f"COMPILE ERROR: {e}")
        return detail

    wasm_path = os.path.join(tmpdir, name + ".wasm")
    with open(wasm_path, "wb") as f:
        f.write(compiled.wasm_bytes)

    node_out = run_node_oracle(wasm_path, calls, read_memory_bytes)
    if "loadError" in node_out:
        detail["passed"] = False
        detail["lines"].append(f"NODE REJECTED our encoded module: {node_out['loadError']}")
        return detail

    inst = Instance(compiled.wasm_bytes)

    for call, node_res in zip(calls, node_out["results"]):
        func, args = call["func"], call["args"]
        py_trap = None
        py_val = None
        try:
            py_val = inst.call_by_name(func, args)
        except WasmTrap as e:
            py_trap = str(e)
        except RuntimeError as e:
            py_trap = f"RuntimeError: {e}"

        node_val = node_res.get("value")
        node_trap = node_res.get("trap")

        if (py_trap is None) != (node_trap is None):
            detail["passed"] = False
            detail["lines"].append(
                f"  ✗ {func}{tuple(args)}: TRAP MISMATCH — python={py_trap!r} node={node_trap!r}"
            )
        elif py_trap is not None:
            detail["lines"].append(f"  ✓ {func}{tuple(args)}: both trap ({py_trap})")
        elif py_val != node_val:
            detail["passed"] = False
            detail["lines"].append(f"  ✗ {func}{tuple(args)}: VALUE MISMATCH — python={py_val} node={node_val}")
        else:
            detail["lines"].append(f"  ✓ {func}{tuple(args)} = {py_val}  (python == node)")

    if read_memory_bytes:
        py_mem = list(inst.memory.data[:read_memory_bytes]) if inst.memory else [0] * read_memory_bytes
        node_mem = node_out.get("memory")
        if node_mem != py_mem:
            detail["passed"] = False
            detail["lines"].append(f"  ✗ MEMORY MISMATCH (first {read_memory_bytes} bytes)")
        else:
            detail["lines"].append(f"  ✓ linear memory matches byte-for-byte (first {read_memory_bytes} bytes)")

    return detail


def main():
    import tempfile

    all_passed = True
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, (calls, mem_bytes) in CORPUS.items():
            rn_path = os.path.join(DEMO_DIR, name)
            detail = verify_file(rn_path, calls, mem_bytes, tmpdir)
            status = "PASS" if detail["passed"] else "FAIL"
            print(f"[{status}] {detail['name']}")
            for line in detail["lines"]:
                print(line)
            if not detail["passed"]:
                all_passed = False
            print()

    if all_passed:
        print(f"ALL {len(CORPUS)} PROGRAMS VERIFIED — python interpreter and Node's native")
        print("WebAssembly engine agree on every call and every trap, byte for byte.")
        return 0
    else:
        print("VERIFICATION FAILED — see mismatches above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
