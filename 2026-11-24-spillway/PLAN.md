# Spillway — Plan

## Concept
Spillway is a **compiler back-end register-allocation laboratory**. It takes a small
three-address IR (virtual registers, basic blocks, loops, memory) and compiles it to a
machine that has only **K physical registers**, using interchangeable allocators. It then
*executes both versions* and proves they agree, while measuring what the allocator cost
(spills, moves, cycles).

## Why it's interesting
Register allocation is the classic NP-hard-in-theory / heuristic-in-practice step of every
compiler (graph colouring ≡ interference graph colouring). Chaitin–Briggs colouring with
conservative coalescing and linear scan make completely different trade-offs
(quality vs. compile speed); seeing them side by side — on real loops, with a cost model
that weights spill code by loop depth — is the educational payoff. Nothing in this repo
has built a compiler back-end allocator before.

## Architecture (Go 1.24, stdlib only)
```
text IR ──parse──▶ Function(CFG) ──validate──▶ liveness (bitset dataflow)
                                   │                │
                                   │        ┌───────┴────────┐
                                   │   interference graph   live intervals
                                   │        │                    │
                                   │  Chaitin–Briggs/Appel   Poletto linear scan
                                   │  (coalesce, freeze,     (+ move hints)
                                   │   optimistic spill)
                                   └─ spill rewriting loop (temps, stack slots) ──▶ allocated code
allocated code ──▶ VM (K regs, cost model) ◀── IR interpreter (∞ regs)  ⇒ differential check
```
Package `sp` (library) + `cmd/spillway` (CLI) + `examples/*.ir` + `demo.sh`.

## Feature list
| # | Feature | Tier |
|---|---------|------|
| 1 | IR text parser/printer/validator + CFG + iterative bitset liveness + natural-loop depth + reference interpreter | **required** |
| 2 | Graph-colouring allocator: Chaitin–Briggs/Appel with Briggs-conservative coalescing, freeze, optimistic spilling, loop-weighted spill cost, spill-rewrite loop | **required** |
| 3 | Linear-scan allocator (Poletto/Sarkar) with furthest-end spilling and move-hint reuse; plus "naive" spill-everything baseline | **required** |
| 4 | Code generation to a K-register machine + cost-model VM (spill ld/st, moves, cycles counted) + differential verifier + independent interference checker | **required** |
| 5 | Random structured program generator + differential fuzzer (`fuzz`) across allocators and K | stretch |
| 6 | K-sweep (`sweep`) comparing allocators across register counts | stretch |
| 7 | Self-contained HTML report: interference graph SVG, live-range charts, sweep chart, annotated asm (light/dark) | stretch |

Required = 1–4, stretch = 5–7. Target: ship all seven.

## Semantics notes (decided up-front)
* 64-bit signed words; `div`/`rem` by zero yield 0 (total semantics, so fuzzing is clean).
* Data memory: 256 words, addresses masked with `&255`. Step limit guards against non-termination.
* Using a possibly-undefined vreg is a validation error.
