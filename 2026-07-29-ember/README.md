# Ember

A from-scratch JIT compiler: a small C-like language, compiled directly
to real x86-64 machine code and executed on the CPU via
`mmap(PROT_EXEC)` + `ctypes` — no bytecode layer, no interpreter loop in
the hot path. See [PLAN.md](PLAN.md) for the full design rationale.

**Status: Phase 4 (stretch + polish) complete.** All 4 required features
work end-to-end against real generated machine code; 4 real bugs found
by hostile review are fixed (see [REVIEW.md](REVIEW.md)), plus one real,
measured, disclosed limitation (native stack overflow on extreme
non-tail recursion — verified to match real `gcc -O0`'s behavior
exactly, not an Ember-specific defect). A 4th stretch feature (constant
folding) is shipped on top of the original 3.

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
   precedence-climbing parser, positioned syntax errors, plus a static
   semantic-check pass (`ember/semcheck.py`) both the interpreter and the
   JIT run before doing anything else, so "is this program valid" has one
   shared, control-flow-independent answer instead of the JIT silently
   being stricter than the interpreter (see REVIEW.md finding #1).
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
8. **Constant-folding optimizer** (`ember/optimize.py`, `--opt` flag on
   `run`/`compare`/`bench`/`viz`) — folds any subexpression built
   entirely out of literals down to one literal before codegen, and
   folds `&&`/`||` consistently with their runtime short-circuit
   semantics (a known-deciding constant left side drops the right
   subexpression entirely, matching what the short-circuit codegen
   would do anyway) — *without* ever folding away a division/modulo
   whose divisor is a known-zero constant, or the INT64_MIN / -1
   overflow case, so the runtime error guards still fire exactly like
   un-optimized code. The interpreter always runs the original,
   unmodified AST, so it stays the ground-truth oracle optimized output
   is checked against. Demonstrated shrinking a real example from 466
   bytes of machine code to 133 (see `ember demo`'s optimizer section).

## Known, disclosed limitation

Ember has no stack-depth guard and no tail-call optimization, so a
sufficiently deep non-tail-recursive JIT'd call eventually overflows the
real OS thread stack and the process receives an uncatchable `SIGSEGV`
— exactly like an equivalent `gcc -O0`-compiled C function would (verified
directly, see REVIEW.md). Measured safe on this box's default 8 MiB stack
up to roughly 100,000 levels of recursion for a single-local function;
segfaults somewhere between 100K and 200K. A production JIT would add a
guard-page stack-overflow trap or a growable stack; both are legitimate
techniques and both are out of scope for a from-scratch one-day build.

## Where a human could take this next

- A real register allocator (linear-scan or graph-coloring) instead of
  the current "every temporary round-trips through the real stack"
  strategy — codegen would get both smaller and faster without changing
  any of the calling-convention or encoding work.
- Arrays/pointers and a stack-allocated buffer type, so Ember could
  express algorithms (sorting, matrix ops) that need more than scalars.
- A guard-page-based stack-overflow trap (mmap a guard page below each
  thread's stack, catch the resulting SIGSEGV with a `sigaltstack`
  handler, turn it into a catchable Ember error) — the real fix for the
  disclosed recursion-depth limitation above.
- Floating point (SSE scalar ops, a second register file, a second ABI
  class in the calling convention).
- A second target architecture (AArch64) behind the same AST, to see how
  much of `codegen_x64.py`'s *structure* (not its bytes) carries over.
