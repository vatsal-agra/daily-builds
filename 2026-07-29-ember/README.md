# Ember

A from-scratch JIT compiler: a small C-like language, compiled directly
to real x86-64 machine code and executed on the CPU via
`mmap(PROT_EXEC)` + `ctypes` — no bytecode layer, no interpreter loop in
the hot path. See [PLAN.md](PLAN.md) for the full design rationale.

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end against real generated machine code. Phase 3 (adversarial
review) next.

## Quickstart

```
python3 -m ember.cli run examples/fib.em fib 20          # JIT-execute, print result
python3 -m ember.cli interp examples/fib.em fib 20        # same, via the tree-walking interpreter
python3 -m ember.cli compare examples/gcd.em gcd 1071 462 # interpreter vs JIT vs real gcc
python3 -m ember.cli ast examples/gcd.em                  # print the parsed AST
python3 -m ember.cli disasm examples/gcd.em --fn gcd      # real objdump listing of the emitted code
python3 -m ember.cli bench examples/fib.em fib 27         # measured interpreter-vs-JIT wall time
python3 -m ember.cli viz examples/fib.em --out report.html --bench-fn fib --bench-args 27
python3 -m ember.cli demo                                 # run everything end to end
```

## The language

64-bit signed integers, `let`/assignment, `if`/`else`, `while`, top-level
`fn` definitions (up to 6 parameters — the System V register-argument
limit, enforced not silently truncated), recursion and mutual recursion,
the full arithmetic/comparison/logical operator set with real
short-circuit `&&`/`||`. See `examples/*.em`.

## Implemented so far

1. **Front end** — hand-written lexer + recursive-descent/
   precedence-climbing parser, positioned syntax errors.
2. **Reference interpreter** — tree-walking evaluator with 64-bit
   wraparound arithmetic matching real hardware, used as the
   ground-truth oracle for everything else.
3. **x86-64 JIT backend** (`ember/asm.py` + `ember/codegen_x64.py`) — a
   hand-rolled machine-code encoder (REX/ModRM, no table lookups),
   correct System V AMD64 calling convention (rdi/rsi/rdx/rcx/r8/r9,
   16-byte call-site stack alignment tracked at compile time), real
   control flow via backpatched relative jumps/calls, assembled into an
   `mmap(PROT_EXEC)` buffer and invoked directly through
   `ctypes.CFUNCTYPE` — the CPU runs it exactly like a `gcc -O0` function
   with the same signature.
4. **Differential correctness harness** — every example program's result
   is checked interpreter-vs-JIT (and, when the box has `gcc`,
   vs.-transpiled-C too) bit-for-bit, across recursion, mutual recursion,
   a 6-argument function (forces r8/r9 handling), and short-circuit
   proofs (not just truth tables).

**Stretch:**

5. **objdump oracle** (`ember/disasm.py`) — the raw bytes the encoder
   produces are independently decoded by the box's real `objdump`;
   `ember demo` asserts the expected instruction mnemonics show up.
6. **gcc oracle** (`ember/transpile_c.py`) — an AST→C transpiler feeds the
   same source to the box's real `gcc -O2 -fwrapv`, runs it, and checks
   its answer against both the interpreter and the JIT.
7. **Interactive HTML report** (`ember/report.py`, `ember/cli.py viz`) —
   source / AST / real objdump disassembly per example, plus a genuine
   measured interpreter-vs-JIT benchmark (not an invented speedup
   number), dark/light theme aware.

## Next

Phase 3: adversarial review — hunt for encoding bugs, calling-convention
edge cases, and CLI robustness gaps, then fix everything found.
