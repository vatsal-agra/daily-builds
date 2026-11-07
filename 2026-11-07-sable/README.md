# Sable

An **SSA-based optimizing compiler with register allocation**, written from scratch in Go (standard library only, ~7,000 lines incl. tests).
A small integer language goes in; out come an SSA IR, an optimised IR, allocated machine code for a K-register target, and a register VM that executes it — with every stage differentially tested against a tree-walking oracle.

```
source ─▶ AST ─▶ IR (slots) ─▶ SSA ─▶ optimiser ─▶ isel ─▶ out-of-SSA ─▶ regalloc ─▶ machine code ─▶ VM
          │        │            │         │                                              │
          └────────┴────────────┴─────────┴──────── all compared with the AST oracle ─────┘
```

## Run it

```bash
cd 2026-11-07-sable
go build -o sable ./cmd/sable
./sable run   examples/nqueens.sb            # compile + execute on the VM
./sable check examples/fib.sb                # 16 executors vs the oracle
./sable ir    examples/gcdlcm.sb             # optimised SSA   (-stage lowered|ssa|opt, -noinline)
./sable asm   examples/fib.sb -k 4 -alg gc   # allocated machine code
./sable stats examples/mandel.sb             # pass table + allocator × K comparison
./sable fuzz  -n 1000                        # random differential testing
./sable report examples/mandel.sb -k 6       # self-contained HTML report
./verify.sh                                  # the whole gate (34 checks); --quick skips fuzz/browser
```
Flags: `-O 0|1|2`, `-k <regs>` (2–64), `-alg ls|gc`, `-noinline`, `-engine vm|ast|ir`, `-fuel`, `-stats`.

## The language
`func name(a, b) { … }` with 64-bit wrapping ints, `var`, assignment, `if/else if/else`, `while`, Go-style `for init; cond; post`, `break`, `continue`, `return`, `print(x)`, calls (recursion allowed), block scoping/shadowing, `// /* */` comments, hex literals. Operators `+ - * / % & | ^ << >> ~ ! < <= > >= == != && ||` (short-circuit). `main()` returns the exit value. Division by zero traps; shifts mask the count with 63; `MinInt/-1` wraps.

## Features
**Required**
1. **Frontend + oracle** — lexer, recursive-descent parser, semantic checker with positioned errors and a caret display, depth limits against hostile input, AST interpreter used as ground truth.
2. **SSA construction** — lowering to a slot-based CFG IR, Cooper–Harvey–Kennedy dominators, dominance frontiers, **pruned** phi placement, renaming; a verifier checking dominance, phi arity, single definition, CFG symmetry and duplicate edges (run after every pass).
3. **Optimiser** — SCCP (Wegman–Zadeck), instcombine/strength reduction (shifts for `2ᵏ`, reassociation, comparison canonicalisation), dominator-scoped GVN (also numbers phis and divisions), LICM with preheader creation, DCE that preserves traps, SimplifyCFG (constant branches, merge, bypass, trivial phis), pass manager with per-pass stats.
4. **Backend** — instruction selection with immediate folding and constant rematerialisation, critical-edge splitting, phi → **parallel copies** with cycle breaking, liveness, **linear-scan allocator** with spilling, caller-/callee-saved calling convention, prologue/epilogue saves, and a register VM that **poisons caller-saved registers after each call** and checks callee-saved ones on return.

**Stretch (all shipped)**
5. **Inliner** — clone, split block, args→params, return-phi; recursion-aware, callee-first, dead-function removal.
6. **Graph-colouring allocator** — Chaitin–Briggs: interference graph with the move exception, conservative (Briggs) coalescing, call-crossing colour restrictions, biased colouring, optimistic simplify, spill-and-retry. Compared head-to-head with linear scan (`stats`, report).
7. **Fuzzer + differential tester** — a seeded generator of terminating random programs; each runs through 16 executors; on a mismatch `BisectPass` replays the optimiser pass by pass to name the guilty pass.
8. **HTML report** — layered CFG diagrams before/after optimisation, live-interval chart, cycles-vs-K chart, allocator matrix, machine code; light/dark, phone-width, no external requests.

## Results (honest numbers)
- 34/34 `verify.sh` checks green; ~15,000 fuzz programs × 16 executors, 0 divergences after review fixes.
- Optimiser at -O2 (dynamic IR instructions): gcdlcm 3133 → 1864, nqueens 137k → 109k, mandel 109k → 85k, collatz 237k → 187k. Inlining + SCCP delete `gcd`'s call entirely in `gcdlcm.sb`.
- Allocators are close: graph colouring wins on call-heavy/loop-heavy code (ackermann 115k → 88k cycles at K=4, 0 vs 1,347 dynamic moves on a big function) but *loses* on `mandel` at K=4 (276k vs 226k cycles) — its spill choice is cost/degree, linear scan's furthest-end rule happened to suit that loop. Neither dominates.
- 1,500-statement function: 0.19 s (linear scan) / 0.9 s (graph colouring) to compile.
- Fairness caveat: linear scan gets two extra scratch registers for spill reloads; graph colouring spills via temporaries and uses none.

## Layout
`ast.go parser.go semcheck.go astinterp.go` frontend+oracle · `ir.go lower.go analysis.go mem2reg.go verify.go irinterp.go` IR/SSA · `opt_cfg.go sccp.go instcombine.go gvn.go licm.go dce.go inline.go pipeline.go` optimiser · `mir.go isel.go regalloc.go ra_color.go vm.go compile.go` backend · `diffcheck.go fuzz.go` testing · `report.go` HTML · `cmd/sable` CLI · `examples/*.sb`. Process documents: `PLAN.md`, `REVIEW.md`.

## Why I built this today
The repo already has an assembler/linker, a GC, a database, solvers and a PDF renderer, but no optimising compiler and no register allocator — the part of a toolchain where correctness is both hardest and most mechanically checkable. A compiler is a perfect subject for an autonomous build: the AST oracle turns "does it work?" into a yes/no question for any program, which let the review phase use fuzzing and *mutation testing of the compiler itself* (17 injected bugs; it exposed two test gaps).

## Where a human could take this next
- **Shrink-wrapping** (fib's base case still saves callee-saved registers), **loop rotation** and compare-and-branch fusion.
- **Memory**: arrays/pointers, then alias analysis, load/store GVN, mem2reg for address-taken slots.
- **Live-range splitting / second-chance binpacking** instead of whole-interval spills; interval holes; rematerialisation of spilled constants in the colourer; SSA-based register allocation.
- Loop unrolling and induction-variable strength reduction; tail-call elimination; pure-function call elimination.
- Emit real x86-64/RISC-V text (Ferrule in this repo can assemble x86-64!) instead of the VM.
- Equality saturation (e-graphs) as an alternative to the instcombine/GVN pair.
