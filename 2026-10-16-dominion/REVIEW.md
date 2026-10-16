# Adversarial review (Phase 3)

I attacked the Phase 2 build the way a hostile reviewer would: scale it, feed it hostile input, run it with
broken environment assumptions, and — the most useful step — **mutation-test the test suite** (inject a
plausible bug into one pass, see whether anything notices). Findings are numbered; every one has a regression
test or a line in `scripts/recheck.sh`, which re-runs all reproductions (`./scripts/recheck.sh` → all green).

## Findings and fixes

| # | Severity | Finding (how it was found) | Fix |
|---|----------|----------------------------|-----|
| R1 | high | **Quadratic compile time.** A 3 000-statement function took 8.8 s, a 50 000-term expression 5.3 s. pprof: `Func.ReplaceAllUses` swept the whole function once per replaced value (SCCP, GVN, trivial-phi removal, SimplifyCFG merges) and `Verify`'s predecessor check was O(blocks × edges). | New `ir.Replacer` batches replacements and applies them in one sweep (`Func.Apply`); passes resolve operands lazily. Verifier pred/succ cross-check is now a single hash-map comparison. Results: 8.8 s → 0.5 s, 5.3 s → 0.3 s. |
| R2 | medium | **Runaway program blocked for 14 s** (default fuel was 2·10⁹ steps) with no way to change it. | Default fuel 2·10⁸ and a `-fuel` flag on `dom run`. |
| R3 | high | **Unbounded output**: `while 1 { print(…) }` grew memory until the fuel ran out (the run took > 60 s and gigabytes). | Both the interpreter and the VM trap with `output limit exceeded` after 1 MiB of output. |
| R4 | low | `-9223372036854775808` could not be written (lexer rejected 2⁶³ even under unary minus). | Lexer reads literals as uint64; only a directly negated `2^63` is accepted. Test in `front`. |
| R5 | low | IR parse errors printed `file.ir:ir:3: …` (double prefix). | `line N: …`. |
| R6 | high | **`select` was a dead opcode**: defined, interpreted, register-allocated, but *nothing ever produced it*, so none of it was exercised by the fuzzer (found when the "sccp select arm" mutant survived 400 fuzz programs). | New `ifconv` pass (diamonds/triangles → `select` with a speculation cost budget), included in -O2/-O3, plus hand-written IR cases using `select` directly. Mutants in SCCP's select handling and in ifconv's operand order are now killed. |
| R7 | medium | First version of `ifconv` **made collatz 15 % slower** (it speculated a `div`, 12 cycles in the VM cost model, on every iteration). | Arms are speculated only when their summed cycle cost ≤ 4. Added signed div/rem-by-power-of-two strength reduction and `x % 2^k == 0 → (x & (2^k-1)) == 0` to InstCombine: collatz -O2 went from 458 k to 273 k cycles. |
| R8 | low | Verifier let an `alloca` appear as a phi operand or `ret` operand (an escaping slot would silently defeat mem2reg/MemOpt's no-escape assumption). | Rejected with a clear message; tests in `ir/ir_test.go`. |
| R9 | medium | **Inliner alloca re-zeroing was untested** — mutant "do not zero inlined allocas" survived all tests, because a call site that executes once never observes stale memory. | Added IR case `inline_alloca_in_loop` (call inside a loop) and pass orders that run `inline` before `mem2reg`; mutant killed. |
| R10 | medium | **Signed division by 2^k bias untested** — mutant "x/4 → x>>2" survived (rounds toward −∞ for negatives). | `TestStrengthReducedDivision` runs ±, MinInt64, MaxInt64 operands through every level and the VM; mutant killed. |
| R11 | low | My own "no speedup" test compared *IR interpreter steps*, which is the wrong metric once strength reduction trades one expensive instruction for several cheap ones. | Test now compares VM cycles. |
| R12 | caught by verifier | While adding expansion in InstCombine, the compaction slice aliased `b.Instrs`, overwriting not-yet-visited instructions (`instruction appears twice`). Found immediately because every pass runs under `Verify` in tests. | Dedicated `kept` slice. |
| R13 | low | A function with > 64 parameters failed late, in the backend, with an error that mentions no source position. | Frontend limit of 32 parameters with a located diagnostic (backend keeps its own 64 limit for hand-written IR). |
| R14 | meta | Three of my hand-computed expectations in `testdata/cases.ir.txt` were wrong (multi-entry loop, live-across-calls, array_dynamic); an `irreducible` case violated dominance. | The interpreter-at-O0 oracle disagreed with my numbers; I re-derived each by hand and fixed the *test data*, never the oracle. The cases file still pins the oracle's output, so a drifting interpreter fails loudly. |

## Mutation analysis of the suite (what the review is built on)

Each mutant is a one-line plausible bug; "killed" means some test or the fuzzer reported it.

| Mutant | Result |
|--------|--------|
| `x - c → x + c` sign error (InstCombine) | killed by fuzzer (seed 1) |
| LICM hoists loads from slots stored in the loop | killed (fuzzer) |
| register allocator: ignore "interval crosses a call" | killed (fuzzer, VM poisons caller-saved regs at return) |
| callee-saved registers not restored in epilogue | killed |
| parallel copy without cycle breaking | killed (fuzzer + `swap_cycle` case) |
| MemOpt: stores never kill aliasing known values | killed |
| DCE: stores kept live without a live load / dropped incorrectly | killed |
| `x * 2^k → x << (k+1)` | killed |
| SimplifyCFG merges blocks with 2 preds | killed |
| SCCP select arm inverted | **survived → R6** → killed after fix |
| mem2reg initial value 0 → 1 | killed by hand-written cases (frontend always initialises, so only raw IR can see it) |
| inliner skips zeroing | **survived → R9** → killed after fix |
| div by 2^k without bias | **survived → R10** → killed after fix |
| ifconv swaps select arms | killed |

## Known limitations (deliberately not "fixed")

* **Out-of-bounds array access is undefined behaviour for the optimizer.** The interpreter and VM trap, but
  passes may delete a dead OOB load/store or reorder it relative to a `print`. (Division by zero *is*
  preserved in order: trapping `div`/`rem` are never removed, hoisted or speculated.) The fuzzers therefore
  generate in-bounds programs and skip mutants whose baseline traps out-of-bounds.
* **Call-depth traps are not preserved by inlining / tail-recursion elimination** — an unbounded recursion that
  overflows at -O0 may run (in a loop) at -O3.
* **Register allocation uses whole-interval spilling and single `[start,end]` hulls** (no lifetime holes, no
  splitting), so values can look live across a call they are not live across and get a callee-saved
  register unnecessarily. Correct but not optimal; documented in the README's next steps.
* Spill slots are never shared between non-overlapping spilled values.

## Fresh run-through

`./scripts/recheck.sh` re-executes the reproduction for R1–R5, R13 and the Go regression tests for R6–R11;
it prints `none of the REVIEW.md findings reproduce`. In addition 3 000 generated programs, 3 000 mutated-IR
modules and the full test-suite pass at the time of writing (see Phase 5 for the final numbers).

---

# Phase 5 addendum — what verification found

Phase 5 ran `scripts/mutants.py` (41 mutants, run in parallel on private copies of the tree, a hung test run
counts as a kill). The first full pass killed 35 of 41; the 6 non-kills were each analysed rather than waved away:

| # | Result | Analysis → action |
|---|--------|-------------------|
| V1 | **real compiler gap found by a new test** | The unroller refused any loop whose entry edge is a *conditional* branch (`if c { for … }`), because it demanded a plain-`br` preheader. Fixed by reusing LICM's `ensurePreheader`; test `TestUnrollKeepsValuesFlowingIntoALoopExitJoin`. |
| V2 | equivalent code | Mutant "unroll: exit-block phi not remapped" survived because the explicit remap was redundant with the later whole-function `Replacer` sweep. The dead code was **deleted** and the mutant replaced by "live-outs not remapped" (killed). |
| V3 | test gap | "memopt: stores never kill aliasing entries" and "loads keep stores pending" survived: no test had two *different SSA values holding the same runtime index*. Added IR cases `alias_store_then_load`, `alias_pending_store` and pass lists that run `memopt` without prior inlining/constant folding (which had been turning every index into the same constant). Both killed. |
| V4 | test gap | "trapping div treated as pure" survived: every `div` in the corpus was *used*, so DCE never had a chance to delete a trap. Added `unused_trapping_div` and `invariant_div_not_hoisted` (zero-trip loop with a loop-invariant `100 / 0`). Killed. |
| V5 | test gap | "`&&` evaluates only its left side" survived (the fuzzer's 60-program `-short` budget didn't hit it). Added an exhaustive `&&`/`||` truth-table test over value, `if`, `!(…)` and `while` contexts including evaluation-order side effects. Killed. |
| V6 | precision gap | "SCCP ignores executable edges" survived: it changes *precision*, not correctness. Added `TestSCCPUsesOnlyExecutableEdges` (a phi whose other input comes from a provably-dead edge must fold). Killed. |

Two more mutants failed to compile or merely timed out in the first run (harness bugs, not product bugs): the
harness now reports "does not compile" separately and treats a 300 s test hang as a kill ("simplifycfg: merge
with 2 preds", "mem2reg: wrong successor value" and "continue skips for-step" all turn into infinite loops).

**Final result: 41 killed, 0 survived, 0 invalid.**

## Final numbers

* `go test -count=1 ./...` → all 8 packages pass (75 test cases; `go vet` clean).
* `dom fuzz -n 2000 -seed 100000` → 1999 programs agree in every configuration (88 of them trap identically), 1 skipped, **0 failures**.
* `dom fuzz -ir -n 4000 -seed 100000` → 1562 valid mutated-IR modules agree everywhere (the rest are rejected by the
  verifier, non-terminating, or hit out-of-bounds UB and are skipped), **0 failures**.
* `./demo.sh` green; `./scripts/recheck.sh` green; the HTML report renders without page errors in headless Chromium in light and dark.
