# Conflux — Adversarial Review (Phase 3)

I attacked my own build as a hostile reviewer: malformed input, degenerate
instances, API hygiene, UX rough edges, and correctness under fuzzing. The
*engine* held up extremely well — see "What survived" — but the I/O surface had
real problems.

## Correctness fuzzing (what survived)
- **Brute-force oracle, 3000 random instances** (n ≤ 10): every SAT/UNSAT
  verdict matched exhaustive `2^n` enumeration. 0 mismatches.
- **Model verification:** all 800 SAT models satisfied their formula.
- **Proof verification:** all 2200 UNSAT results carried a DRAT proof that the
  *independent* checker accepted. 0 bad proofs.
- **Python↔JS parity:** 500 shared instances, identical verdicts. 0 diffs.
- **Edge cases:** empty CNF → SAT; empty clause → UNSAT; contradictory units
  `(x)(¬x)` → UNSAT (proof ok); all-tautology clauses → SAT; duplicate literals;
  unit-propagation chains; variable-index gaps — all correct.
- **Performance:** AI-escargot (hardest 9×9 sudoku) solved & validated;
  25-queens in ~57 ms; 50-var random-3-SAT at the α=4.26 threshold in ~1 ms.

So the algorithm is solid. The bugs were all on the edges.

## Issues found & fixed

### F1 — CLI vomits raw Python tracebacks on bad input  *(severity: high, UX)*
- `conflux sudoku "123"` → `ValueError: expected 81 cells` **as a traceback**.
- `conflux solve bad.cnf` where the file has a junk line → `ValueError: invalid
  literal for int()` **as a traceback** with no hint where.
- `conflux phase --vars 2` → traceback from `random.sample`.
- A real tool reports a clean error, not a stack trace.
**Fix:** (a) `CNF.from_dimacs` now raises a line-numbered, descriptive
`ValueError`; (b) `main()` wraps dispatch and prints `error: <msg>` to stderr
with exit code 2 for the expected user-error exceptions.

### F2 — Inconsistent verdict strings  *(severity: low, consistency)*
`solve` prints `s UNSATISFIABLE` but `sudoku` printed `s UNSAT`. DIMACS-style
output should be uniform.
**Fix:** unsolvable sudoku now prints `s UNSATISFIABLE`.

### F3 — Dead, misleading API parameters  *(severity: low, hygiene)*
`Solver.__init__(..., rng_seed=...)` and `Solver.solve(assumptions=...)` were
never used — they imply features (randomized search, assumption-based solving)
that don't exist.
**Fix:** removed both. The solver is fully deterministic and that is now honest.

### F4 — Visualizer default instance is UNSAT  *(severity: low, UX)*
The page auto-ran a random instance that happened to be UNSAT, so a first-time
visitor never sees a *satisfying model* (and the sudoku-style payoff) without
fiddling. The most instructive first impression shows a SAT model being built.
**Fix:** default random instance retuned (n=16, ratio 3.2) so the auto-run lands
on SAT with a handful of conflicts — showing both learning *and* a model; the
verdict banner now also states "model verified: true".

### F5 — `color custom` with no `--vertices` silently does nothing  *(severity: low, UX)*
`conflux color custom 3` (forgetting `--vertices`) printed nothing and exited 0,
which looks like success.
**Fix:** a custom graph with 0 vertices is now a clear error telling the user to
pass `--vertices` (and optionally `--edges`).

## Re-test gate
After the fixes, a fresh run-through of every item above hits **zero** of the
listed issues (verified in Phase 5's test suite + the demo script).
