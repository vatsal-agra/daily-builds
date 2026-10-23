# REVIEW — adversarial pass over Gatecraft

I attacked the Phase 2 code as a hostile reviewer: wrote independent oracles (a `math/big`
Verilog interpreter, an explicit-state model checker, a BLIF interpreter, a VCD parser),
random-netlist fuzzers, mutation tests, and a pile of malformed inputs. Every finding below was
**reproduced first, then fixed, then pinned with a regression test**. "Found by" says what caught it.

## Bugs

| # | Severity | Finding | Found by | Fix | Regression test |
|---|----------|---------|----------|-----|-----------------|
| R1 | high | In a combinational `always`, `y = 0; y = a;` was reported as *latch inferred*: `muxLit(True, new, Undef)` returned `Undef` because it checked the "undefined" marker before the (constant-true) condition. | code read while writing the statement fuzzer | `muxLit` short-circuits constant conditions first | `TestUnconditionalOverwriteIsNotALatch` |
| R2 | high | Reading **one bit** of a vector resolved the **whole** vector, so `assign c[5] = g[4] \| p[4] & c[4]` was rejected as a combinational loop (every carry-lookahead adder hit it). | `TestAdderArchitecturesEquivalent` | ranged reads (`readRange`) resolve only the bits referenced | `TestBitLevelDependenciesDoNotCreateFalseLoops` |
| R3 | critical | The optimiser's removal record collapsed "alias of X" into "unobservable" when X later became unobservable. The checker then lost the tie `s1 == s0` and **rejected a correct optimisation** (and a weaker checker would have been unsound the other way). | optimiser fuzz, random netlist seed 124 | alias chains keep pointing at the unobservable survivor; checker proves the tie inductively with an *intra-design* obligation (`Obligation.Side`) | `TestAliasOfUnobservableRegisterKeepsItsTie`, `TestOptimizerFuzz` |
| R4 | critical | Equivalence used two *separate* SAT encodings, so two copies of the **same** 8-bit multiplier were "hard": the emit round-trip test ran >2 min, and a bounded check of the 8-bit counter against its own round trip burned 330 k conflicts and gave up. | `TestExamplesEmitAndReparse` hang | miter built in **one structurally-hashed AIG** (identical logic collapses before SAT), then direct SAT with a small budget, then FRAIG sweeping + larger budget; same for the bounded unrolling | `TestIdenticalMultipliersNeedNoSearch` (0 conflicts) |
| R5 | high | `CheckComb` **panicked** ("unbound source node") when a pass left registers in the netlist that were no longer observable (SAT-sweeping the TinyCPU). Liveness was computed per design, but a live register's next-state cone can reach registers dead in the other design. | `gatecraft opt examples/tinycpu.v` | `relevantState` computes the cross-design closure to a fixpoint | `TestOptimizingTheTinyCPUIsFullyVerified` |
| R6 | medium | A legal design was rejected: `assign c = ~a; always @* begin a = x; b = a ^ c; end` reported a combinational loop, because a procedural block was evaluated atomically. | hostile test design | a running block answers reads of its own outputs with the value computed so far, and **fails loudly** if the block assigns that bit again afterwards (so no silent wrong answer) | `TestPeekThroughOwnOutputIsNotALoop` |
| R7 | low | Counterexamples named 1-bit outputs `cout[0]`. | CLI run | name omits the index for 1-bit ports | `TestCounterexampleNamesSingleBitOutputsPlainly` |
| R8 | low | An AIGER literal beyond `M` was reported as "combinational cycle"; empty input reported "no modules found" with no file name. | `TestReadAIGERErrors`, CLI | precise messages; reader rewritten without the earlier placeholder/dead code | `TestReadAIGERErrors`, `TestNoModulesMessageNamesTheFile` |
| R9 | low | Silent truncation/zero-extension of instance port connections. | review of `installInstance` | non-fatal `warning:` diagnostics (printed by every command) | `TestPortWidthWarnings` |
| R10 | perf | SAT `value()` did a branch + shift per literal test; propagation is ~75 % of runtime. | pprof of a 9-bit multiplier miter | per-literal value array: 14.6 s → 10.7 s | all SAT tests |

## Lazy shortcuts I looked for (and what I did)

* **"Tests that cannot fail".** I mutation-tested the new fuzzers: flipping `LtV`'s polarity, the divider
  quotient bit, or the barrel shifter's overflow combinator each fail `TestExpressionsAgainstBigIntReference`;
  swapping the branches in `merge` or dropping the dynamic-write condition fail
  `TestProceduralCodeAgainstInterpreter`. All restored.
* **Counterexamples are never trusted.** Every CEX/trace (equivalence, bounded, property) is replayed in
  the bit-parallel simulator, and the fuzzers require `Confirmed == true`.
* **Proof claims are cross-checked** against brute force: `TestPropertyCheckerAgainstExplicitState` BFS-es
  the reachable state space of 300 random sequential netlists (with `assume`s) and requires every PROVED to
  be truly invariant, every FAILED to occur at exactly the shortest violating cycle, and no BOUNDED verdict to
  hide a violation inside the bound.
* **Placeholder logic.** None left: no stubs, no hard-coded outputs. The only constants are the documented
  conventions (divide-by-zero → all-ones quotient / dividend remainder; flops reset to 0 unless initialised).

## Limitations I accept (and document in the README)

* Unsigned arithmetic only (`signed`, `>>>` are rejected with a message); no x/z; no async reset, tri-state,
  memories-as-arrays, `generate`, functions/tasks, delays, or multi-edge sensitivity lists.
* Procedural-block granularity: signals assigned in an `always @*` are resolved together; two blocks cannot
  drive different bits of one vector.
* Sequential equivalence is by **state matching** (registers paired by name, plus the optimiser's removal
  record) or **bounded unrolling**; two machines with *different state encodings* can only be compared up to
  a bound (reported as such, never as a proof).
* The SAT engine is a compact CDCL, not MiniSat-fast: `a*b ≡ b*a` is proved at 8 bits in ~1 s and at
  10 bits in about a minute; beyond the conflict budget (`-conflicts`) the verdict is INCONCLUSIVE.

## Fresh run-through

After the fixes: `go vet ./...` clean, `gofmt -l .` empty, `go test ./...` green, every finding above
re-run through its regression test, and the CLI error-path battery (empty file, syntax error, missing
file, two candidate tops, bad `-P`, interface mismatch, unsupported constructs) prints one-line
diagnostics with `file:line:col`. No listed issue reproduces.
