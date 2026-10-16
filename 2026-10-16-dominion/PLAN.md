# Dominion — Plan

## Concept
**Dominion** is an optimizing compiler *middle- and back-end* built from scratch in Go (stdlib only):
a small C-like language ("Dom") is lowered to a textual **SSA intermediate representation**, pushed through a
real pass pipeline (dominators → mem2reg → sparse conditional constant propagation → GVN → LICM → inlining →
DCE …), then compiled out of SSA, register-allocated by **linear scan** with spilling and a caller/callee-saved
calling convention, and run on a small register-machine VM that counts cycles.

Every stage is independently executable: the IR has a reference **interpreter**, so any pass can be checked by
running the program before and after it. A built-in **differential fuzzer** generates random terminating
programs and asserts `interp(O0) == interp(O2) == vm(O2, N regs)` for output, return value *and* traps.

## Why it is interesting
Earlier builds in this repo covered front-ends (parsers, HM inference), VMs/JITs, and many runtimes — but never
the part in the middle that makes compiled code fast: SSA construction (Cytron/Cooper-Harvey-Kennedy dominance
frontiers), Wegman-Zadeck conditional constant propagation, dominator-scoped value numbering, loop-invariant
code motion with preheader insertion, SSA destruction with parallel-copy sequentialisation, and register
allocation under pressure. These are the algorithms inside LLVM/GCC/V8 — and they are famously easy to get
subtly wrong, which is why the differential fuzzer is a first-class feature rather than an afterthought.

## Architecture
```
 source (.dom) ──front──▶ IR (alloca/load/store, non-SSA) ──ir.Verify──▶
      opt pipeline: simplifycfg · mem2reg · sccp · instcombine · gvn · licm · inline · dce · (loop-simplify)
 ──▶ SSA IR ──backend──▶ machine code (vregs → linear scan → physical regs/spills) ──▶ vm (cycle-counted)
          ▲                         ▲
       ir.Interp (oracle)      text asm listing
```
Packages: `ir` (data model, printer, parser, verifier, interpreter), `front` (lexer/parser/lowering),
`opt` (dominators, loops, passes, pass manager), `backend` (isel, out-of-SSA, liveness, linear scan, emit),
`vm` (machine ISA + executor), `fuzz` (random program generator + differential oracle), `cmd/dom` (CLI).

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **Front-end + SSA IR toolchain**: Dom language → IR; IR text printer *and* parser (round-trip); strict verifier (CFG consistency, phi arity, def-dominates-use); reference interpreter with traps (div0, OOB, fuel, stack depth) | **required** |
| 2 | **SSA construction**: Cooper-Harvey-Kennedy dominators, dominance frontiers, `mem2reg` phi placement + renaming, trivial-phi cleanup, CFG simplification | **required** |
| 3 | **Optimizer**: SCCP (Wegman-Zadeck, executable-edge lattice), instcombine/algebraic simplification, dominator-tree GVN/CSE, LICM with preheaders, function inlining, aggressive DCE + dead-alloca removal; configurable pipeline (`-O0/-O1/-O2`, `-passes=...`) with per-pass stats | **required** |
| 4 | **Native-style backend**: critical-edge splitting, phi → parallel copies, liveness, linear-scan register allocation with spilling, caller/callee-saved ABI, register-machine VM with cost model and asm listing | **required** |
| 5 | **Differential fuzzer**: random structured program generator; checks IR-interp(O0) vs each pass vs IR-interp(O2) vs VM at several register counts; minimiser for failing seeds | stretch |
| 6 | **Visual reports**: Graphviz DOT / self-contained HTML CFG viewer with dominator tree, loop nesting, per-pass before/after IR diff | stretch |
| 7 | Tail-recursion elimination & bounded loop unrolling | stretch |
| 8 | Benchmark table: cycles & instruction counts per `-O` level on the bundled example programs | stretch |

## Definition of done
All required features exercised by `go test ./...` and `demo.sh`; fuzzer runs thousands of seeds clean;
REVIEW.md lists adversarial findings and each one is fixed and regression-tested.

## Outcome
All 8 features shipped (4 required + 4 stretch: differential/mutated-IR fuzzer with reducer, HTML explorer,
tail-recursion elimination + full loop unrolling + if-conversion, benchmark table). Two additions beyond the
plan came out of the review phase: if-conversion (`select` was otherwise dead) and the mutation-analysis harness.
