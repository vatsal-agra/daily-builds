# Ember — a from-scratch JIT compiler to real x86-64 machine code

## The concept

Every prior "language" build in this repo's history has targeted an
interpreter or a virtual machine: Coil compiles to its own bytecode and
runs it on a hand-written stack VM; Kiln decodes and interprets real
`.wasm` binaries; Unify statically infers types but never executes past a
tree-walker. None of them ever hand the CPU actual machine instructions.

Ember does. It is a small, from-scratch, ahead-of-time-per-call **JIT
compiler**: source text for a tiny C-like language goes through a
hand-written lexer and recursive-descent parser into an AST, and from
there straight to **real x86-64 machine code bytes** — correct REX
prefixes, ModRM/SIB encoding, a genuine System V AMD64 calling convention
(integer args in rdi/rsi/rdx/rcx/r8/r9, 16-byte stack alignment at call
sites, real `push`/`call`/`ret`), assembled into an executable buffer via
`mmap(..., PROT_EXEC)` and invoked directly through `ctypes` — the exact
mechanism real JITs (V8, LuaJIT, PyPy) use to hand generated code to the
CPU. There is no bytecode layer and no interpreter loop in the hot path:
once compiled, a function *is* machine code, and the CPU runs it exactly
as it would a `gcc -O0` function with the same signature.

## Why this is interesting

1. **It is verifiable against reality, not just against itself.** A
   hand-rolled tree-walking interpreter gives the ground-truth semantics
   for every test program. A hand-rolled AST→C transpiler plus the box's
   real `gcc` gives a *second*, fully independent oracle: the same source
   program, compiled by a real production compiler, must return the same
   integer. And the raw bytes Ember emits are disassembled by the box's
   real `objdump` — an independent tool that shares zero code with
   Ember's own encoder — so "the encoder claims it emitted `add rax, rcx`"
   is checked against "the world's own disassembler agrees it did."
   Three independent oracles (interpreter / gcc / objdump) triangulating
   on one JIT is a stronger correctness story than any one of them alone.
2. **Calling convention correctness is a real, checkable constraint.**
   Stack must be 16-byte aligned at every `call` site or real C library
   functions crash; register argument passing has to route through
   rdi/rsi/rdx/rcx/r8/r9 in the right order even when an earlier argument
   expression needs its own nested call. Get it wrong and the process
   segfaults — there is no "close enough."
3. **The whole point of a JIT is speed** — recursive Fibonacci run through
   native code versus the same AST walked by the interpreter gives a real,
   measured wall-clock number, not a marketing claim.

## Architecture

```
source.em
   │  lexer.py        (hand-written scanner, positioned errors)
   ▼
tokens
   │  parser.py        (recursive-descent, Pratt-style precedence climbing)
   ▼
AST (ast_nodes.py)
   ├──────────────┬───────────────────────┬───────────────────────┐
   ▼              ▼                       ▼                       ▼
interpreter.py   codegen_x64.py        transpile_c.py          (viz/report)
(tree-walk,      (hand-rolled x86-64   (AST -> equivalent C,
 ground truth)    encoder: REX/ModRM/   fed to the box's real
                  SIB, stack-slot       gcc as a 2nd oracle)
                  locals, real calling
                  convention)
                     │
                     ▼
               jit.py: mmap(PROT_EXEC) + ctypes.CFUNCTYPE
                     │
                     ▼
               native machine code, executed by the real CPU
                     │
                     ▼
               disasm.py: shells to the box's real `objdump` to
               independently decode the emitted bytes (3rd oracle)
```

The language itself ("Ember source", `.em` files): 64-bit signed integers
only, `let` locals, `if`/`else`, `while`, top-level `fn` definitions with
up to 6 parameters (the System V register-argument limit — enforced, not
silently ignored), recursion and mutual recursion, `return`, the full
arithmetic/comparison/logical operator set with correct precedence
(`* / %` > `+ -` > comparisons > `&&` > `||`, with real short-circuit
evaluation via jumps, not eager evaluation of both sides).

## Feature list

**Required (4):**

1. **Front end.** Lexer + recursive-descent/precedence-climbing parser
   producing a full AST for the language described above, with
   line/column-anchored syntax errors.
2. **Reference interpreter.** A tree-walking evaluator that runs the AST
   directly — the ground-truth semantics oracle everything else is
   checked against.
3. **x86-64 JIT backend.** A hand-rolled machine-code encoder (REX
   prefixes, ModRM/SIB, correct instruction lengths) implementing real
   stack-slot locals, real System V argument passing (rdi/rsi/rdx/rcx/
   r8/r9), 16-byte call-site stack alignment tracked at compile time, and
   real control flow (`jmp`/`jcc` with backpatched relative offsets,
   `call`/`ret`) — assembled into a buffer and executed via
   `mmap(PROT_EXEC)` + `ctypes.CFUNCTYPE`, i.e. run directly by the CPU.
4. **Differential correctness harness.** Every test program is run both
   ways (interpreter and JIT) and the results must match bit-for-bit,
   across a battery that includes recursive functions (factorial,
   Fibonacci), mutual recursion (is-even/is-odd), GCD, a 6-argument
   function (forces r8/r9 argument-register handling), and short-circuit
   `&&`/`||` (proven by a side-effecting-counter-style test, not just a
   truth table).

**Stretch (2 required minimum, aiming for 3):**

5. **objdump oracle.** Feed the raw bytes Ember's encoder produced to the
   box's real `objdump -D -b binary -m i386:x86-64`, parse its output,
   and confirm it decodes into the intended instruction sequence — an
   independent tool, sharing no code with the encoder, checking the
   encoder's own claims about what it emitted.
6. **gcc oracle.** A from-scratch AST→C transpiler; the transpiled C is
   compiled with the box's real `gcc` and run as a subprocess. Its
   printed result must match both the interpreter's and the JIT's result
   for every test program — a second fully independent semantic check.
7. **Interactive HTML report + real benchmark.** A self-contained,
   dark/light-aware HTML page showing, per example program: source,
   AST (indented tree), and the real objdump-derived assembly listing
   side by side, plus a genuine measured wall-clock benchmark
   (interpreter vs. JIT wall time on recursive `fib(28)` or similar) — an
   actual speedup number, not an invented one.

## Risks / honesty notes to track into REVIEW.md

- x86-64 encoding bugs are exactly the kind of thing that "looks like it
  works" on a happy-path test and then segfaults or silently
  miscomputes on a slightly different program (odd argument counts,
  deep recursion, negative numbers, division). The differential harness
  against the interpreter *and* gcc is the main defense; a segfault
  during Phase 3's adversarial pass is a signal to fix code generation,
  never to narrow the test.
- 16-byte stack-alignment bugs are notoriously silent right up until they
  aren't (they only bite when a called function itself needs alignment,
  e.g. deep in libc) — worth a dedicated stress case even though Ember
  never calls out to libc for arithmetic itself.
- Division/modulo by zero and integer overflow need explicit, defined
  behavior (not "whatever `idiv` happens to fault on") documented and
  tested, not silently left to a SIGFPE.
