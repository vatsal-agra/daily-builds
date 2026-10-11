# REVIEW — adversarial pass over Phase 2

I attacked the build as a hostile reviewer: hand-written nasty programs, CLI misuse, and reading my own code for
unsound shortcuts. Each finding below was **reproduced first**, then fixed (status at the bottom of each item).

## Findings

| # | Severity | Finding | Reproduction | Fix |
|---|----------|---------|--------------|-----|
| R1 | high (silent wrong answer) | Integer literals wrap silently: `return x*77 + 300` at 8 bits analyzes `300` as `44`, so reports describe a program the author did not write. | `let y = 300;` with `--width 8` prints no error | Literals outside `[-2^(W-1), 2^W-1]` are now a located error: `line 3: literal 300 does not fit in 8 bits` (checked by both interpreter and explorer). |
| R2 | high (semantics bug) | `else if` re-evaluated calls hoisted from the *outer* condition because the pending-call buffer was not reset: `if (f(x) > 100) { } else if (x > 5) {…}` ran `f` twice (prints `7 7 99` for x=7). | `/tmp` repro c1.dl: `delve run -i x=7` printed 7 twice | Pending buffer is reset when parsing an `else if`. Regression test added. |
| R3 | medium (misleading output) | Loop-free programs reported "No bugs found (up to the loop bound)", and exhaustive runs never said they were exhaustive. The wording logic was effectively dead code. | `analyze a5.dl` | Report now distinguishes: *proved bug-free for all inputs* (nothing truncated, no limits hit, no solver give-ups) vs *bug-free within bounds* with the reason listed. |
| R4 | high (hang) | No solver budget: a hard 32-bit multiplicative query can run indefinitely and the wall-clock `--timeout` is only checked between states. A 32-bit `a*b == c*K` program took 14 s even though it was easy; a harder one would never return. | `a4.dl --width 32` | `Smt` takes a conflict budget (`--solver-budget`, default 100k). Exhausting it raises `Unknown`; the executor abandons that path, counts it, and the report says results are incomplete. `minimize()` falls back to the un-minimized model instead of failing. |
| R5 | medium (crash) | A 3000-term `x+x+…` expression died with "program too deeply nested" — the recursion limit is tiny for a tool that nests ASTs. | `b2.dl` | CLI runs inside a large-stack thread with a high recursion limit. |
| R6 | low (UX) | `run -i typo=4` silently ignored the unknown input name, so users believe they supplied a value. | c1/a5 repro | Warns on stderr listing the program's real input names. |
| R7 | low (UX) | A program with zero feasible paths (e.g. `assume(0)` or an empty `input(5, 1)` range) printed an empty table with no explanation. | `assume(0);` | Explicit "no feasible path" diagnosis. |
| R8 | low (UX) | Path conditions were unreadable: `not((0 == ite((n < 0), 1, 0)))` instead of `n < 0`; `not((3 < a))` instead of `a <= 3`. | abs.dl report | `bv2bool` sees through `ite(c,1,0)`; the printer flips negated comparisons. |
| R9 | medium (test gap) | Nothing exercised `input()` inside loops (labels `v`, `v#2`, …) across solver and interpreter, a place where the two sides could drift apart. | c2.dl | Added loop-input test; labels verified by replay. |

## Things I checked that were fine
* Bit-blaster vs. concrete semantics: differential tests on every operator at widths 4, 5, 8, 12 (including non-power-of-two shift widths and division by zero semantics).
* Path partitioning: for 25 random programs and **every** input pair at 5 bits, exactly one generated path matches and its predicted result/prints/trap equals the interpreter's. This is the soundness+completeness check for the executor.
* Short-circuit guards: `b > 0 && a / b > 1` yields no division bug; `b > 0 || a / b > 1` does.
* Shadowed `let` in nested blocks and recursion param scoping.

## Gate: fresh run-through
After the fixes `tests/test_review.py` replays every item above (R1–R9) and `tests/run_all.py` is green; the
original repro programs no longer misbehave.
