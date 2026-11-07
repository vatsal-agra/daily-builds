# REVIEW — adversarial pass over Sable (Phase 3)

Method: (1) hostile hand-written programs and CLI abuse, (2) scale/limits attacks,
(3) a random-program differential fuzzer (≈14,000 programs across seeds and sizes,
every program run through 16 executors), (4) **mutation testing of the compiler
itself** — 17 deliberately injected bugs, to learn whether my own tests would notice
(a test suite that never fails proves nothing), (5) reading the generated code for
quality. Every defect below was fixed and now has a regression test.

## Defects found (all FIXED)

| # | Severity | Finding | How found | Fix | Regression test |
|---|----------|---------|-----------|-----|-----------------|
| 1 | **critical** | Register allocator deleted `mov r,r` self-copies *together with the spill store that followed them* — a spilled phi destination never reached memory (K=2, `lcg.sb`: fuel exhaustion, loop never advanced). | corpus run at K=2 (during Phase 2) | removed copy still emits its pending `st` | `TestCorpusBackend` (K=2..12 × both allocators × O0/O2) |
| 2 | **high** | Compile time was **quadratic**: a 1,500-statement function took **41 s** (LICM recomputed all loops once per loop; `Dominates` walked the idom chain, ~90 % of time in map lookups). | scale attack with a generated 1,500-line program + pprof | dominator-tree DFS numbering → O(1) dominance; LICM computes loops once, creates all preheaders, re-analyses once; DF construction no longer linear-scans. 41 s → 0.19 s (LS) / 0.9 s (GC) | `TestCompileScales` |
| 3 | **high** | Pathological nesting (`((((…` 3 M deep, `-----…`, `{{{{…`, 1 M-term `1+1+…`) crashed the compiler with an **unrecoverable Go stack overflow** (fatal error, not a panic). | hostile-input attack | parser tracks expression-tree depth (limit 2000) and block nesting (limit 300); clean positioned error | `TestNestingLimits` |
| 4 | medium | `check` on an endless loop ran **> 100 s** (oracle gave up, then every one of the 16 executors was given 20× the fuel). `run`'s default 2·10⁹ fuel took 11 s to stop an infinite loop. | hostile program: `while 1 {}` | executors only get 50× what the oracle consumed (10 k when the oracle ran out); `run` default 3·10⁸; `stats` refuses non-terminating programs; `check` says "nothing compared" instead of "all agree" | `TestCheckEndlessLoopReturnsQuickly` |
| 5 | medium | **Test gap — parallel-copy cycles.** Mutant "parallel copy without cycle breaking" *survived* my whole suite and 600 fuzz programs: no test produced a phi swap (`a,b = b,a` in a loop). | mutation testing | direct unit test of `parallelCopy` semantics (swap, 3-cycle, cycle+reader, self-copy, imm, fan-in) + end-to-end swap/rotate programs | `TestParallelCopySemantics`, `TestPhiSwapCycle` |
| 6 | low | **Test gap — pruned SSA.** Mutant "unpruned phi placement" survived (the zero-fallback made it semantically harmless, but it bloats the IR). | mutation testing | explicit phi-count assertion | `TestPrunedPhis` |
| 7 | low | Error caret printed the *entire* 4 KB source line for long lines. | CLI abuse | window of ±40 columns around the error | manual (CLI) |
| 8 | low | `stats`/`check` summary said "all 16 executors agree" even when all had been skipped. | reading output | counts compared vs skipped | `TestCheckEndlessLoopReturnsQuickly` |
| 9 | info | Three of my *expected values* in `TestEdgeExpectedValues` were wrong (`eight-params` is 324, `mutual-recursion` 11); the compiler and the oracle agreed with each other and were right. Hand-computed expectations are the weakest link — the differential harness is the real oracle. | test failure | corrected | — |

## Mutation-testing scoreboard (17 injected faults)

Caught by unit tests: no callee-saved restore · call-crossing values in caller-saved regs ·
mul-by-2ᵏ off by one · SCCP folds `x/0` · DCE drops a trapping division · phi copies in
reverse order · LICM hoists without checking operands · unmasked shift counts · `x-x→x` ·
GC ignores call-crossing constraint · bypass-empty-block ignores edge overlap · parallel-copy
without cycle breaking (after finding #5).
Caught only by the fuzzer: GVN treating `sub` as commutative · LICM hoisting a trapping `div`.
**Survived (equivalent or undetectable mutants, analysed):**
- *LS shares a register when `a.End <= cur.Start`.* Under RPO layout a value can only start exactly at a block's first slot through a back edge, which forces the other interval to span the whole loop — I could not construct a program where it matters. The strict `<` is kept anyway because it is the safe reading.
- *Unpruned phi placement* — semantically harmless, now asserted structurally (#6).
- *VM without poisoning.* With the allocator's call-crossing rule also broken the suite still failed (callees overwrite caller-saved registers anyway), so poisoning is a safety net, not the sole detector. It stays: it is what makes a *stale-but-lucky* value impossible.

## Quality observations (not defects — recorded in README "where next")
- No **shrink-wrapping**: `fib`'s base case still saves/restores two callee-saved registers it never touches.
- No **loop rotation**: loops pay one extra `jmp` per iteration; no fused compare-and-branch.
- Linear scan does no copy coalescing (the graph colourer does: it removes ~100× more moves on the 1,500-statement stress program: 10 vs 1,347 dynamic `mov`s).
- Inliner not yet written at the end of Phase 3 (stub returning 0) — implemented in Phase 4 (stretch #5).

## Fresh run-through (gate)
After the fixes: `go vet`, `gofmt -l` clean; all unit/edge/scale tests green; fuzz seeds 1–300,
1000–7000, 9000–12000 (funcs=6) and 50000–52000 (funcs=6): **0 findings**; the three
nesting bombs and the endless loop now return in milliseconds with a clear message.
None of the nine issues above reproduces.
