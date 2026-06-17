# Adversarial Review

I attacked Backjump as a hostile reviewer: malformed input, degenerate clauses,
heuristic edge cases, certificate trustworthiness, and UX. Findings below, each
with the fix and how the fix was verified. A fresh run-through now hits zero of
these.

## Correctness findings

### 1. Unit clauses were not propagated at decision level 0
**Severity: high.** The solver attached unit clauses to watch lists but never
*enqueued* their literals at the root. It only ever discovered them by branching
into the opposite phase and then learning the unit back — which mislabels decision
levels and would miss root-level conflicts in formulas that are decided purely by
top-level implication.
**Fix:** `solve()` now enqueues every unit clause at decision level 0 before the
first propagation, and reports UNSAT immediately on contradictory units.
**Verified:** unit-only SAT instances now solve with 0 decisions; the 16k-trial
differential fuzz (below) exercises many unit-heavy formulas.

### 2. Duplicate literals put a clause in a watch list twice; tautologies wasted watches
**Severity: medium (latent).** A clause like `[1, 1, 2]` was watched on literal `1`
twice; `[1, -1, …]` (a tautology) consumed two watches for a clause that is always
satisfied. The two-watched-literal scheme assumes the two watches are distinct, so
this was a latent invariant violation.
**Fix:** the `Solver` constructor now normalises every clause — it removes
duplicate literals and drops tautologies — before building watch lists.
**Verified:** a dedicated 4,000-instance fuzz that *deliberately* injects duplicate
and complementary literals into clauses matches brute force with zero mismatches.

### 3. The proof checker miscounted clauses with duplicate literals
**Severity: high (found because fix #2 exposed it).** The independent RUP checker's
unit-propagation counted literal occurrences, not distinct variables, so it treated
`[3, 3]` as a two-literal clause and never propagated the unit it actually is. Once
the solver started normalising (fix #2) but the checker did not, a *correct* UNSAT
proof was rejected. This was a real bug in the verifier — exactly the kind of thing
that makes a "verified" answer untrustworthy.
**Fix:** `_Propagator.add` now dedups literals and drops tautologies, matching the
solver's view of each clause.
**Verified:** 16,000 random instances across four seeds (including duplicate- and
tautology-laden clauses) — every SAT model and every UNSAT proof verified, zero
mismatches vs brute force.

### 4. UNSAT solves produced no terminal trace event
**Severity: low (visualizer).** The trace recorder emitted a `sat` event on success
but nothing on UNSAT, so the visualizer's replay ended with `result = null` and the
"current step" panel never announced unsatisfiability.
**Fix:** all four UNSAT exit points now route through `_conclude_unsat()`, which
records the proof's empty clause *and* a terminal `unsat` trace event.
**Verified:** the PHP(4,3) bundle's last event is now `{"type": "unsat"}`; the node
replay harness reconstructs a consistent final state for both SAT and UNSAT.

## Non-correctness findings

### 5. The proof checker is quadratic on large refutations
**Severity: medium (performance, not correctness).** RUP checking re-propagates the
whole accumulated formula for every proof step, so cost grows ~quadratically: PHP(7,6)
verifies in ~1.2 s (1,119 steps) but PHP(8,7) takes ~47 s (5,800 steps).
**Resolution:** this is acceptable for an independent correctness oracle, but the
demo and test suite deliberately stay at modest sizes (≤ PHP(7,6)). Documented as a
known limitation and a clear "where to take this next" item (forward-checking /
watched-literal DRAT checker). Not a shrink of any required feature.

### 6. The CLI surfaced raw tracebacks for bad input
**Severity: medium (UX).** A missing DIMACS file or malformed CNF dumped a Python
stack trace instead of a clean error message.
**Fix (Phase 4):** `main()` now catches `FileNotFoundError` and input/parse
`ValueError`s and prints a one-line diagnostic with a non-zero exit code; the DIMACS
parser raises precise messages.

### 7. Random-CNF generation could loop forever (test harness)
**Severity: low (tooling).** An early fuzz generator looped trying to pick `k`
distinct literals from fewer than `k` variables (e.g. width 3 over 1 variable).
**Fix:** `random_ksat` clamps clause width to `min(k, num_vars)`.

## Things I tried to break and could not
- Empty input / zero clauses / empty clause in the formula — all handled (SAT, SAT,
  and immediate UNSAT respectively).
- N-Queens n = 2, 3 — correctly UNSAT with verified proofs; n = 1, 4, 5, 6 SAT.
- Invalid Sudoku (a digit repeated in a row) — correctly UNSAT.
- Free variables in a model — filled deterministically; model still verifies.
- VSIDS activity overflow path — `rescale + heap rebuild` exercised by construction
  and never corrupts ordering.
- 24,000+ total random instances across all fuzz runs — zero solver/oracle
  disagreements, every certificate independently verified.
