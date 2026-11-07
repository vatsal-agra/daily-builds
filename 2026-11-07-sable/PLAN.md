# Sable — PLAN

## Concept
Sable is a from-scratch **optimizing compiler middle- and back-end**: a small
imperative language (64-bit ints, functions, recursion, loops) is lowered to a
CFG IR, converted to **SSA** (dominators, dominance frontiers, pruned phi
placement), optimised by a pass pipeline (SCCP, GVN, LICM, instcombine, DCE,
CFG simplification, inlining), taken **out of SSA** (critical-edge splitting,
parallel-copy sequentialisation) and **register-allocated** for a machine with
K registers (caller-/callee-saved split, spilling), then executed on a
register VM that *poisons caller-saved registers on every call*.

## Why it is interesting
The repo has an assembler/linker (Ferrule), a GC (Cairn), a DB, solvers... but
no optimising compiler and no register allocator. Compilers are the best
testbed for **differential testing**: every stage must agree with a tree-walking
oracle on every program, for every K, so correctness is checkable by machine
rather than by eye. Honest performance numbers (dynamic instruction counts,
spill loads/stores) fall out for free.

## Architecture
```
source ─lex/parse/check─▶ AST ──────────────────────────▶ AST interpreter (ORACLE)
                          │
                          ▼ lower
                     IR (slots, load/store) ─▶ IR interpreter
                          │ mem2reg (idom, DF, pruned phis)
                          ▼
                       SSA IR ─▶ verifier (dominance, phi arity, single def) ─▶ IR interpreter
                          │ passes: simplifycfg, sccp, instcombine, gvn, licm, dce, inline
                          ▼
                    optimised SSA ─▶ IR interpreter
                          │ isel (imm folding, const remat), split critical edges, phi→parallel copies
                          ▼
                    machine IR (vregs) ─ liveness ─▶ linear scan │ graph colouring (Briggs + coalescing)
                          ▼ spill rewrite, prologue/epilogue saves
                    machine code (K regs) ─▶ register VM (poisoning, counters)
```
Single Go package `sable` (+ `cmd/sable` CLI), standard library only.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Frontend: lexer, parser, semantic checker with positioned errors, AST **oracle interpreter** (wrapping int64, traps) | **required** |
| 2 | Lowering + **SSA construction** (CHK dominators, dominance frontiers, pruned phis) + **SSA verifier** + IR interpreter | **required** |
| 3 | **Optimiser**: SCCP, instcombine/strength reduction, dominator-scoped GVN, LICM, DCE, CFG simplification, pass manager with per-pass stats and verify-after-every-pass | **required** |
| 4 | **Backend**: out-of-SSA, isel, liveness, **linear-scan allocator** with spilling + calling convention, register VM with counters & caller-saved poisoning | **required** |
| 5 | Function **inlining** (clone + split + return-phi) | stretch |
| 6 | **Graph-colouring allocator** (Chaitin–Briggs, conservative coalescing, spill-and-retry) and head-to-head comparison with linear scan | stretch |
| 7 | **Random-program fuzzer + differential tester** with pass-bisection to name the guilty pass | stretch |
| 8 | **HTML report**: per-pass CFG diagrams, live-interval chart, allocator comparison table | stretch |

## Semantics (shared by all executors)
- `int` is signed 64-bit, wrapping; `/` and `%` truncate; divide by zero **traps**;
  shifts mask the count with 63; comparisons give 0/1; `&&`/`||` short-circuit.
- Output = sequence of `print` values + return value of `main` (or a trap).
- Stack-overflow (depth > 1000) and out-of-fuel are *resource* outcomes and are
  excluded from differential comparison (inlining legitimately changes depth).

## Gates
Every executor (AST, IR, SSA, each pass, machine code at K = 2..12 with both
allocators) agrees with the oracle on the example corpus and on thousands of
random programs.
