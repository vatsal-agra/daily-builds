# Ember

A from-scratch JIT compiler: a small C-like language, compiled directly
to **real x86-64 machine code** and executed on the CPU via
`mmap(PROT_EXEC)` + `ctypes` — no bytecode layer, no interpreter loop in
the hot path. Once compiled, an Ember function *is* machine code; the CPU
runs it exactly as it would a `gcc -O0` function with the same signature.

Every prior "language" build in this repo's history targeted an
interpreter or a virtual machine (Coil's bytecode VM, Kiln's WASM
interpreter, nine separate from-scratch transformers, Unify's
tree-walking evaluator). None of them ever hand the CPU actual
instructions. Ember does — see [PLAN.md](PLAN.md) for the full design
rationale and [REVIEW.md](REVIEW.md) for the adversarial-review findings.

## What it is

Ember compiles source text through a hand-written lexer and
recursive-descent parser into an AST, then straight to x86-64 bytes:
correct REX prefixes, ModRM/SIB encoding, and a genuine System V AMD64
calling convention (integer args in rdi/rsi/rdx/rcx/r8/r9, 16-byte
stack alignment tracked at every call site, real `push`/`call`/`ret`).
The bytes are assembled into an executable buffer and invoked directly
through `ctypes.CFUNCTYPE` — the same mechanism real JITs (V8, LuaJIT,
PyPy) use.

Three independent oracles verify it, not just each other:

1. **A tree-walking reference interpreter** (ground-truth semantics).
2. **The box's real `gcc`**, via a from-scratch AST→C transpiler — the
   same source, compiled by a production compiler, has to return the
   same answer.
3. **The box's real `objdump`**, independently disassembling the raw
   bytes the encoder produced — a tool sharing zero code with the
   encoder confirms it emitted what it says it emitted.

## How to run it

```bash
cd 2026-07-29-ember

# the full verification suite: unit tests, the CLI demo, and CLI smoke checks
./demo.sh

# or drive the CLI directly:
python3 -m ember.cli run examples/fib.em fib 20            # JIT-execute, print result
python3 -m ember.cli interp examples/fib.em fib 20          # same program, via the interpreter
python3 -m ember.cli compare examples/gcd.em gcd 1071 462   # interpreter vs JIT vs real gcc
python3 -m ember.cli ast examples/gcd.em                    # print the parsed AST
python3 -m ember.cli disasm examples/gcd.em --fn gcd        # real objdump listing of the emitted code
python3 -m ember.cli bench examples/fib.em fib 27           # measured interpreter-vs-JIT wall time
python3 -m ember.cli viz examples/fib.em --out report.html --bench-fn fib --bench-args 27
python3 -m ember.cli run examples/fib.em fib 20 --opt       # constant-fold before compiling
python3 -m ember.cli demo                                   # run everything end to end
python3 -m unittest discover -s tests -v                    # the unit/integration test suite (123 tests)
```

## The language

64-bit signed integers (wrapping two's-complement, matching real
hardware — not Python's arbitrary precision), `let`/assignment,
`if`/`else`, `while`, top-level `fn` definitions (up to 6 parameters —
the System V register-argument limit, enforced not silently truncated),
recursion and mutual recursion, the full arithmetic/comparison/logical
operator set with correct precedence and real short-circuit `&&`/`||`
(proven by construction — see `examples/logic.em`). See `examples/*.em`
for the full set of demo programs (Fibonacci, factorial, GCD, mutual
recursion, primality testing, Ackermann, a 6-argument function, and the
short-circuit proofs).

## Feature list

**Required:**

1. **Front end** — hand-written lexer + recursive-descent/
   precedence-climbing parser with positioned syntax errors, plus a
   static semantic-check pass (`ember/semcheck.py`) both other backends
   run before doing anything else, so "is this program valid" has one
   shared answer instead of the JIT silently being stricter than the
   interpreter (found during adversarial review — see REVIEW.md #1).
2. **Reference interpreter** (`ember/interpreter.py`) — tree-walking
   evaluator with 64-bit wraparound arithmetic matching real hardware,
   the ground-truth oracle everything else is checked against.
3. **x86-64 JIT backend** (`ember/asm.py` + `ember/codegen_x64.py`) — a
   hand-rolled machine-code encoder (no table lookups), a real System V
   AMD64 calling convention, backpatched relative jumps/calls (forward
   references resolved after every label is known — needed for mutual
   recursion), assembled into `mmap(PROT_EXEC)` and invoked through
   `ctypes.CFUNCTYPE`.
4. **Differential correctness harness** (`tests/test_differential.py`,
   `ember demo`) — every example program's result is checked
   interpreter-vs-JIT-vs-gcc, bit-for-bit, across recursion, mutual
   recursion, a 6-argument function (forces r8/r9 handling both at the
   callee's prologue *and* at a caller's argument-marshalling site —
   REVIEW.md #5), and short-circuit proofs.

**Stretch (shipped 4, 2 required):**

5. **objdump oracle** (`ember/disasm.py`) — the raw bytes are
   independently decoded by the box's real `objdump`; both the test
   suite and `ember demo` assert the expected instruction mnemonics
   appear.
6. **gcc oracle** (`ember/transpile_c.py`) — an AST→C transpiler feeds
   the same source to the box's real `gcc -O2 -fwrapv`, runs it, and
   checks its answer against both the interpreter and the JIT.
7. **Interactive HTML report** (`ember/report.py`, `ember/cli.py viz`) —
   source / AST / real objdump disassembly per example, plus a genuine
   measured interpreter-vs-JIT benchmark (not an invented speedup
   number), dark/light theme aware, zero console errors
   (Playwright-verified).
8. **Constant-folding optimizer** (`ember/optimize.py`, `--opt` flag) —
   folds literal subexpressions at compile time, folds `&&`/`||`
   consistently with their runtime short-circuit semantics, and
   deliberately *never* folds away a division/modulo whose divisor is a
   known-zero constant (or the INT64_MIN / -1 case) — those stay real
   runtime operations so the error guards still fire. Demonstrated
   shrinking a real example from 466 bytes of machine code to 133.

## Why I chose this today

This repo has, at this point, built five from-scratch SAT solvers, seven
from-scratch transformer language models, three from-scratch Git-like
VCSes, and five from-scratch ray/path tracers — all genuinely different
builds, but all landing in a handful of well-trodden "toy implementation"
categories (interpreters, VMs, classical algorithms). A JIT compiler that
emits *real, running machine code* is a different kind of claim: it isn't
checkable by "does this look like a reasonable AST" or "does the VM's own
bytecode loop agree with itself" — it's checkable by handing the exact
bytes to `objdump` and asking a tool that has never seen this codebase
whether they mean what they're supposed to mean, and by handing the same
source to `gcc` and asking whether a completely independent compiler
computes the same integer. That's a stronger, more falsifiable
correctness story than most of what "from scratch" usually means, and it
was still genuinely unclaimed territory in this ledger.

## Known, disclosed limitation

Ember has no stack-depth guard and no tail-call optimization, so a
sufficiently deep non-tail-recursive JIT'd call eventually overflows the
real OS thread stack and the process receives an uncatchable `SIGSEGV`
— exactly like an equivalent `gcc -O0`-compiled C function does (verified
directly — see REVIEW.md). Measured safe on this box's default 8 MiB
stack up to roughly 100,000 levels of recursion for a single-local
function; segfaults somewhere between 100K and 200K. A production JIT
would add a guard-page stack-overflow trap or a growable stack; both are
legitimate techniques and both are out of scope for a from-scratch
one-day build.

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

## Verification

- `python3 -m unittest discover -s tests -v` — 123 tests: lexer, parser
  (precedence/associativity/error cases), interpreter (wraparound
  arithmetic, truncating division, short-circuiting), the x86-64 encoder
  independently checked against real `objdump`, the full differential
  battery across every example program (with gcc where available),
  regression tests for all 5 adversarial-review findings, the
  constant-folding optimizer, and CLI subprocess tests (including clean
  error handling for missing files, bad syntax, wrong argument counts,
  non-integer arguments, and division by zero).
- `./demo.sh` — runs the above, then `ember demo` (a self-contained
  showcase of every feature against real assertions, including spinning
  up the real objdump/gcc oracles), then a handful of explicit CLI smoke
  checks.
