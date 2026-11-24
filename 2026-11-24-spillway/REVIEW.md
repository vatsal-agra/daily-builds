# Spillway — Adversarial Review (Phase 3)

I attacked the Phase-2 build as a hostile reviewer: malformed input, hostile CFGs,
scale, resource limits, allocator quality, and — most importantly — *"would my
tests even notice a wrong allocator?"* (mutation testing of the harness itself).

## Findings (all fixed)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | **High (quality)** | Graph colouring spilled ~3× more values than needed on high-pressure code (60 live vars, K=32: **100** variables sent to memory, linear scan only 36). Root cause: the Chaitin cost/degree metric happily picked *one-instruction-long* live ranges (`c = lt a, b; br c, …`) as spill candidates — spilling them cannot help, their reload temp needs a register at the very same point. | Values whose whole live range is ≤ 1 instruction are marked unspillable in every round, for both allocators. Same program/K: 100 → 63 spilled variables, cycles 25.3k (linear) vs 20.9k (colour). |
| 2 | **High (quality)** | Spill-everywhere output was visibly lazy: `spill_st [s], r0` immediately followed by `r0 = spill_ld [s]`, dead stores for never-reloaded slots, and one stack slot per spilled variable even when lifetimes are disjoint. | New post-allocation passes (`sp/postopt.go`): block-local store→load forwarding (drop reload / turn it into a 1-cycle `mov`), dead spill-store removal via slot liveness, stack-slot sharing via interference colouring of slots. `pressure.ir` K=6 colour: 3577 → 2701 cycles. Switchable with `-nopost` so the effect stays measurable. |
| 3 | Medium | Parse errors for "block falls off the end" / "code after a terminator" reported `line 0`. | Parser tracks per-block / per-instruction line numbers; messages now say which block and why. |
| 4 | Medium | A program that never terminates produced three identical, confusing per-allocator rows ("reference run … step limit exceeded", 0 cycles). | `CheckTerminates` runs the reference once up front; `run`/`compare`/`sweep` print one clear message (*"program did not finish within N steps on input [...] (infinite loop?)"*). |
| 5 | Medium | `-k 100000000` was accepted and allocated `K`-sized tables per node (memory bomb). | `MaxK = 1024`, clear error. `K < 3` also rejected with the reason. |
| 6 | Medium (test-suite) | The fuzzer generated blocks in natural layout order only, so layout-sensitive linear-scan numbering bugs could hide. | Generator can randomly permute block layout (entry stays first); the fuzzer does so on every other seed. |
| 7 | Low | Spill code printed as `r0 = spill_ld 15` — ambiguous with an immediate/register. | Printed as `r0 = spill_ld [slot15]`, `spill_st [slot15], r0`. |
| 8 | Low | `run` subcommand carried a dead variable and re-ran the program twice per input without need; `color.go` contained a dead no-coalesce branch. | Cleaned. |
| 9 | Low | Unreachable blocks were silently accepted. | `spillway live` now prints `warning: block X is unreachable`. (Still legal: they are allocated and checked.) |

## Does the test harness actually catch wrong allocators? (mutation testing)

I injected bugs one at a time and confirmed the fuzzer/checkers fail:

| Mutant | Caught by |
|--------|-----------|
| linear scan frees intervals 3 positions too early | independent `CheckAssignment` ("simultaneously live but share r0") |
| coalescing ignores the *constrained-move* test | `CheckAssignment` |
| spill rewrite forgets the store after a def | differential run (`print count differs: 7 vs 2`) |
| Briggs test loosened | "no fixed point" / miscompile |
| forwarding pass stops invalidating on redefinition | differential run |
| dead-store pass deletes every store | differential run |
| slot compaction ignores slot conflicts | differential run |
| linear scan expiry `end <= start` instead of `<` | **survived — proven equivalent**: a value live-in to a block is also live-out of every predecessor, so if the block's first-instruction use is the value's last, no other value can start exactly there. Kept the strict `<` as the documented-correct form. |

## Accepted limitations (documented, not bugs)

* Spilling is *spill-everywhere* (one slot for the whole variable). No live-range splitting.
* Linear scan uses one conservative interval per value (no lifetime holes), as in Poletto & Sarkar's original.
* No pre-coloured registers / calling convention: arguments come from an `arg n` pseudo-instruction.
* `div`/`rem` by zero return 0 and `INT_MIN / -1` returns 0 so every program is total (needed for clean fuzzing).
* Forwarding is block-local; it does not follow values across edges.

## Fresh run-through
Re-ran every probe above (empty program, no `ret`, code after `ret`, infinite loop, huge K, K=2, bad flags, immediates-only operands, overflow, unreachable blocks with undefined reads, `br c, L, L`) — each now produces a precise message or a verified result. Fuzz: 500 programs × 3 allocators × 5 register counts (+ coalescing off) × 5 inputs, zero failures.
