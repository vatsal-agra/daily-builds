# Dominion

*Daily build 2026-10-16 · status: shipped (all 6 phases, 4/4 required + 4/4 stretch features).*

**An optimizing compiler middle- and back-end, written from scratch in Go (standard library only).**
A small C-like language is lowered to a textual **SSA IR**, pushed through a real pass pipeline —
dominators → `mem2reg` → sparse conditional constant propagation → GVN → LICM → inlining → if-conversion →
loop unrolling → DCE — then taken out of SSA, **register-allocated by linear scan** under a real calling
convention, and executed on a cycle-counting register-machine VM. Every stage can be run, inspected and
cross-checked against a reference interpreter, and a built-in **differential fuzzer** hammers all of it.

```
 Dom source ──front──▶ IR (alloca/load/store) ──passes──▶ SSA IR ──backend──▶ DVM machine code ──▶ vm
      ▲                         │  ir.Verify after every pass          │ linear scan, spills, ABI
      └──────────── ir.Interp: the oracle every configuration must agree with ─────────────┘
```

~7 700 lines of Go + ~1 900 lines of tests (75 test cases), two fuzzers, a 41-mutant mutation harness (all 41 killed), an HTML pass explorer.

## Run it

```bash
go build -o dom ./cmd/dom           # or: go run ./cmd/dom <command>
./dom run examples/fib.dom           # compile at -O2 and execute on the VM
./dom bench examples/*.dom           # cycles at -O0..-O3 (each level cross-checked against the interpreter)
./dom report -O3 examples/matmul.dom # → examples/matmul.report.html  (open in a browser)
./demo.sh                            # full tour + verification of every feature (≈1 min, FAST=1 for less)
go test ./...                        # unit, property, differential-fuzz and CLI tests
```

| command | what it does |
|---------|--------------|
| `dom run [-O n] [-regs n] [-interp] [-stats] [-fuel n] f.{dom,ir}` | compile and execute `@main` (VM by default, `-interp` for the IR interpreter) |
| `dom ir [-O n] [-passes a,b] [-trace] [-stats] f` | print the (optimised) SSA IR; `-passes` picks an explicit pipeline |
| `dom asm [-O n] [-regs n] [-report] f` | DVM assembly listing + register-allocation report |
| `dom check f` | parse, verify and interpret |
| `dom bench [-regs n] f…` | cycles for -O0…-O3, refusing to print numbers if any level miscompiles |
| `dom fuzz [-n N] [-seed S] [-regs 4,6,12] [-ir]` | differential fuzzer (generated programs, or mutated IR with `-ir`); failures are auto-minimised |
| `dom report [-O n] [-o out.html] f` | single-file HTML explorer: CFG after every pass, dominator tree, loops, diffs, cycles table |
| `dom passes` | list passes |

Exit status: 0 ok · 1 compile/usage error · 2 bad command · 3 the *program* trapped (output is flushed first).

## The language (Dom) in one screen

```c
fn gcd(a, b) { if b == 0 { return a; } return gcd(b, a % b); }
fn main() {
    var a[8];                                   // fixed-size zero-initialised arrays (never escape)
    for var i = 0; i < 8; i += 1 { a[i] = i * i; }
    var s = 0;
    for var i = 0; i < 8 && s < 100; i += 1 { s += a[i]; if s % 7 == 0 { continue; } }
    print(gcd(1071, 462));                      // prints 21
    return s;
}
```
64-bit wrapping integers, `if/else`, `while`, `for`, `break`/`continue`, short-circuit `&&`/`||`, `+= -= *=`, local arrays,
recursion, `print`. Errors come with a source line and caret. Out-of-range array indexes and division by zero trap.

## Feature list (all shipped)

**Required**
1. **Front-end + SSA IR toolchain** — lexer, Pratt-style parser, lowering with real scoping rules and short-circuit control
   flow; an IR with **printer *and* parser** (round-trips), a **strict verifier** (CFG consistency, phi arity per predecessor,
   def-dominates-use, alloca discipline, call arity), and a **reference interpreter** with traps (÷0, out-of-bounds, fuel,
   stack depth, output limit).
2. **SSA construction** — Cooper-Harvey-Kennedy dominators (checked against the paper's example), dominance frontiers,
   `mem2reg` with iterated-DF phi placement and dominator-tree renaming, trivial-phi cleanup, CFG simplification
   (constant branches, unreachable code, empty-block forwarding, chain merging).
3. **Optimizer** — SCCP (Wegman-Zadeck, executable edges), InstCombine (identities, constant folding, reassociation,
   strength reduction incl. signed `÷2ᵏ`/`%2ᵏ`), dominator-scoped GVN with commutativity, store→load forwarding and
   dead-store elimination, LICM with preheader insertion, a call-graph-aware inliner (re-zeroes callee frames), aggressive
   DCE with write-only-alloca removal. Pipelines `-O0…-O3` or any explicit `-passes` list, per-pass stats, verify-after-each-pass.
4. **Backend** — critical-edge splitting, phi → parallel copies with cycle breaking, liveness dataflow, **linear-scan
   register allocation with spilling**, caller-/callee-saved convention (stack-passed arguments, r0 result), prologue/epilogue
   saves, a VM that **poisons caller-saved registers after every call** so ABI violations explode instead of hiding, and a
   cycle-cost model.

**Stretch (also shipped)**
5. **Differential fuzzer** — random terminating programs (loops, calls, arrays, short-circuit, break/continue, traps), checked
   as interpreter(-O0) = interpreter(-O1/2/3) = text round-trip = VM at 3 register-file sizes = random pass orders; plus a
   **mutated-IR fuzzer** that explores irreducible CFGs, odd phis and `select`; delta-debugging **reducer**.
6. **HTML explorer** — pass-by-pass CFG slider, dominator-tree overlay, loop headers, new-instruction highlighting, cycles bar table, machine code; light/dark.
7. **Tail-recursion elimination** and **full loop unrolling** of constant-trip loops (nested counted loops flatten completely: `matmul` -O3 is 3.1× faster than -O0).
8. **Benchmark table** with built-in correctness gating, plus **if-conversion** (`select`) and a cycle-budgeted speculation model.

Typical results (`dom bench`, 12 registers; cycles from the VM cost model):

```
program           O0 cycles           O1           O2           O3   O0→O3
collatz              686865       287056       273376       273376   2.51x
hash                   5417         2186         1131          936   5.79x
mandel               359757       118549        91600        91600   3.93x
matmul                16693         8133         7167         5416   3.08x
primes                84318        46969        42393        42393   1.99x
```

## How it was verified

* `go test ./...` — per-pass tests that assert the *transformation* (CSE count, hoisted multiply, select created,
  call gone, loop flattened…), not just "output unchanged"; a hand-written IR corpus (`testdata/cases.ir.txt`: swap cycles,
  lost copy, irreducible CFG, multi-entry loops, `select`, 10 parameters, values live across calls…) run through every pass
  list and 4 register files; VM, backend, report and CLI tests.
* `dom fuzz` / `dom fuzz -ir` — thousands of programs per run, zero known failures.
* `scripts/mutants.py` — injects 41 plausible one-line compiler bugs and demands the suite catch each one
  (see REVIEW.md for what this found in the *tests*).
* `scripts/recheck.sh` — re-runs the reproduction of every finding in REVIEW.md.

## Why I built this today

The repo already has parsers, VMs, JITs, a CPU, TLS, a filesystem… but nothing for the part of a compiler that decides
*how fast the result is*. SSA, dominance, SCCP, value numbering, LICM and register allocation are famously easy to get subtly
wrong, so the project is shaped around proving correctness: an independent oracle, a verifier after every pass, an ABI-enforcing
VM, and fuzzers that attack the whole pipeline. It was also a chance to do the thing compilers are rarely shown doing: letting
you *watch* the optimizer work, pass by pass.

## Where a human could take this next

* **Better register allocation:** live-range splitting and lifetime holes (interval hulls make some values look live across
  calls — visible in `dom asm -regs 6 examples/gcd.dom`), spill-slot sharing, loop-depth spill weights, or graph colouring with coalescing.
* **More optimisations:** partial redundancy elimination, induction-variable strength reduction, bounds-check elimination
  (needs a value-range analysis), partial unrolling/vectorisation, interprocedural SCCP, escape analysis for non-local arrays.
* **Language:** globals, pointers/slices (forces alias analysis), strings, structs; a proper type system (the IR is untyped `i64`).
* **Backend:** encode DVM to bytes and emit real x86-64 or RISC-V (the repo's *Silicon* and *Ember* builds are natural partners).
* **Verification:** translation validation (prove each pass's output equivalent with an SMT solver — the repo's *Delve* build
  has one), coverage-guided fuzzing, mutation-guided test generation.
* **Tooling:** DWARF-like source maps in the report, a `--print-after=pass` diff mode, LSP-style diagnostics.

## Layout

```
ir/        data model, printer, parser, verifier, dominators, interpreter, Replacer
front/     lexer, parser, lowering (Dom → IR)
opt/       cfg, mem2reg, instcombine, sccp, gvn+memopt, dce, licm, inline, tre, unroll, ifconv, pipeline
backend/   mir (isel/phi elimination), regalloc (liveness + linear scan), emit (parallel copies, frames)
vm/        DVM ISA, executor, cost model
fuzz/      program generator, differential checker, IR mutator, reducer
report/    HTML explorer (embedded template)
cmd/dom/   CLI
examples/  10 programs   testdata/  hand-written IR cases   scripts/  mutants.py recheck.sh screenshot.js
```
Design notes and the adversarial review live in [PLAN.md](PLAN.md) and [REVIEW.md](REVIEW.md).
