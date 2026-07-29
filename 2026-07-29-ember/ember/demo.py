"""`ember demo` -- a single command that exercises every feature Ember
ships, end to end, through the real CLI-facing API (not a special test
harness): parses every example program, differentially checks
interpreter vs JIT vs (if available) gcc, proves the division-by-zero
and INT64_MIN/-1 guards raise cleanly instead of crashing, runs a real
benchmark, and writes the HTML report. Exits nonzero if anything
disagrees.
"""

import os
import sys

from .parser import parse
from .interpreter import Interpreter
from .codegen_x64 import compile_program
from .errors import EmberRuntimeError
from .transpile_c import run_via_gcc, gcc_available
from .disasm import objdump_available
from .report import generate_report
from .optimize import fold_constants

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXAMPLES = os.path.join(_HERE, "examples")

CASES = [
    ("fib.em", "fib", [0]),
    ("fib.em", "fib", [1]),
    ("fib.em", "fib", [10]),
    ("fib.em", "fib", [22]),
    ("factorial.em", "factorial", [0]),
    ("factorial.em", "factorial", [1]),
    ("factorial.em", "factorial", [15]),
    ("factorial.em", "factorial_rec", [15]),
    ("gcd.em", "gcd", [1071, 462]),
    ("gcd.em", "gcd", [17, 5]),
    ("gcd.em", "gcd", [0, 9]),
    ("parity.em", "is_even", [0]),
    ("parity.em", "is_even", [37]),
    ("parity.em", "is_odd", [37]),
    ("primes.em", "is_prime", [2]),
    ("primes.em", "is_prime", [97]),
    ("primes.em", "is_prime", [100]),
    ("primes.em", "count_primes_below", [50]),
    ("ackermann.em", "ackermann", [2, 3]),
    ("ackermann.em", "ackermann", [3, 3]),
    ("args6.em", "weighted_sum", [1, 2, 3, 4, 5, 6]),
    ("args6.em", "weighted_sum", [-1, -2, -3, -4, -5, -6]),
    ("args6.em", "call_weighted_sum", [10]),
    ("logic.em", "guard", [0, 5]),
    ("logic.em", "guard", [2, 5]),
    ("logic.em", "either", [0, 5]),
    ("logic.em", "either", [2, 3]),
    ("logic.em", "logical_not", [0]),
    ("logic.em", "logical_not", [7]),
]

_program_cache = {}


def _load(fname):
    if fname not in _program_cache:
        with open(os.path.join(_EXAMPLES, fname)) as f:
            source = f.read()
        _program_cache[fname] = (parse(source), source)
    return _program_cache[fname]


def run():
    failures = []
    have_gcc = gcc_available()
    have_objdump = objdump_available()
    print(f"gcc oracle available: {have_gcc}")
    print(f"objdump oracle available: {have_objdump}")
    print()
    print(f"=== differential check: interpreter vs JIT{' vs gcc' if have_gcc else ''} ===")

    for fname, fn, args in CASES:
        program, _ = _load(fname)
        interp_r = Interpreter(program).call(fn, args)
        jit_r = compile_program(program).call(fn, args)
        ok = interp_r == jit_r
        gcc_r = None
        if have_gcc:
            gcc_r = run_via_gcc(program, fn, args)
            ok = ok and interp_r == gcc_r
        status = "PASS" if ok else "FAIL"
        extra = f" gcc={gcc_r}" if have_gcc else ""
        print(f"  [{status}] {fname}:{fn}{tuple(args)} -> interp={interp_r} jit={jit_r}{extra}")
        if not ok:
            failures.append((fname, fn, args, interp_r, jit_r, gcc_r))

    print()
    print("=== runtime error guards (division by zero, INT64_MIN / -1) ===")
    div_program, _ = _load("gcd.em")  # any program will do; write an ad hoc one instead
    div_source = "fn d(a, b) { return a / b; }\nfn m(a, b) { return a % b; }\n"
    div_prog = parse(div_source)
    compiled_div = compile_program(div_prog)
    interp_div = Interpreter(div_prog)

    for label, fn, args in [
        ("division by zero (JIT)", "d", [10, 0]),
        ("division by zero (interpreter)", "d", [10, 0]),
        ("modulo by zero (JIT)", "m", [10, 0]),
        ("INT64_MIN / -1 (JIT)", "d", [-(2 ** 63), -1]),
        ("INT64_MIN / -1 (interpreter)", "d", [-(2 ** 63), -1]),
    ]:
        backend = compiled_div if "JIT" in label else interp_div
        try:
            backend.call(fn, args)
            print(f"  [FAIL] {label}: expected EmberRuntimeError, got no exception")
            failures.append((label, fn, args, None, None, None))
        except EmberRuntimeError as e:
            print(f"  [PASS] {label}: raised cleanly -> {e}")

    print()
    print("=== benchmark: recursive fib(27), interpreter vs JIT ===")
    fib_program, _ = _load("fib.em")
    from .bench import benchmark
    stats = benchmark(fib_program, "fib", [27])
    print(f"  interpreter: {stats['interpreter']['per_call']*1e6:.2f} us/call")
    print(f"  jit:         {stats['jit']['per_call']*1e6:.2f} us/call")
    print(f"  speedup:     {stats['speedup']:.1f}x")

    print()
    print("=== constant-folding optimizer: same answers, smaller code ===")
    fold_src = (
        "fn f(x) {\n"
        "    let a = 2 + 3 * 4;\n"
        "    let b = (1 < 2) && (3 == 3);\n"
        "    let c = 0 && (10 / 0 > 1);\n"  # must NOT fold away the division guard
        "    return a + b + c + x;\n"
        "}\n"
    )
    fold_prog = parse(fold_src)
    folded = fold_constants(fold_prog)
    unopt_len = len(compile_program(fold_prog).code_bytes)
    opt_len = len(compile_program(folded).code_bytes)
    interp_r = Interpreter(fold_prog).call("f", [100])
    jit_r = compile_program(folded).call("f", [100])
    ok = interp_r == jit_r and opt_len < unopt_len
    print(f"  [{'PASS' if ok else 'FAIL'}] f(100): interpreter={interp_r} jit(folded)={jit_r}  "
          f"code size {unopt_len}B -> {opt_len}B")
    if not ok:
        failures.append(("optimizer", "f", [100], interp_r, jit_r, None))
    # a divisor of a *known-zero* constant must still raise at runtime, not
    # get folded away (or, worse, raised as a Python exception at compile time).
    div_zero_src = "fn g() { return 5 / 0; }\n"
    div_zero_prog = parse(div_zero_src)
    try:
        compile_program(fold_constants(div_zero_prog)).call("g", [])
        print("  [FAIL] constant division by zero should still raise EmberRuntimeError")
        failures.append(("optimizer-div-guard", "g", [], None, None, None))
    except EmberRuntimeError as e:
        print(f"  [PASS] constant-divisor-zero still raises cleanly through the optimizer -> {e}")

    print()
    print("=== objdump independent disassembly oracle ===")
    if have_objdump:
        from .disasm import disassemble
        program, _ = _load("fib.em")
        compiled = compile_program(program)
        insns = disassemble(compiled.code_bytes)
        mnemonics = {i.mnemonic for i in insns}
        expected_present = {"push", "pop", "call", "ret", "cmp", "movabs", "add", "sub"}
        missing = expected_present - mnemonics
        if missing:
            print(f"  [FAIL] objdump listing is missing expected mnemonics: {missing}")
            failures.append(("objdump", "fib", [], None, None, None))
        else:
            print(f"  [PASS] objdump independently decoded {len(insns)} instructions "
                  f"from fib.em's compiled code, including all of {sorted(expected_present)}")
    else:
        print("  objdump not available, skipped")

    print()
    print("=== writing HTML report ===")
    extra_examples = []
    for fname in ["factorial.em", "gcd.em", "parity.em", "primes.em", "ackermann.em", "args6.em", "logic.em"]:
        prog, src = _load(fname)
        extra_examples.append((fname, src, prog))
    main_prog, main_src = _load("fib.em")
    html = generate_report(
        os.path.join(_EXAMPLES, "fib.em"), main_prog,
        bench_fn="fib", bench_args=[27],
        extra_examples=extra_examples,
    )
    out_path = os.path.join(_HERE, "viz", "report.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html)
    print(f"  wrote {out_path}")

    print()
    if failures:
        print(f"DEMO FAILED: {len(failures)} case(s) disagreed")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    else:
        print(f"DEMO PASSED: {len(CASES)} differential cases + error guards + benchmark + objdump oracle, all green")
