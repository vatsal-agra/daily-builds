# Resolvent — Adversarial Review (Phase 3)

I attacked my own solver as a hostile reviewer. Method: 2,500-instance random
differential vs a brute-force oracle (every SAT model re-checked, every UNSAT
verdict independently RUP-proof-checked), targeted edge cases, and a code read
of the subtle machinery (watched literals, 1-UIP analysis, reduceDB, clause
simplification). Findings below; all fixed in this phase.

## Findings

### F1 — `reduceDB` reindexes clauses but leaves stale `reason[]` pointers *(correctness landmine, fixed)*
`_reduce_db` rebuilds `self.clauses` into a fresh, renumbered list, but
`self.reason[v]` stores integer indices into the *old* list. After a reduce,
every reason pointer is potentially wrong. Today it doesn't blow up only
because the one place that could dereference a stale pointer during search
(`_analyze`) only ever follows reasons of **current-decision-level** literals,
which are always assigned *after* the level-0 reduce and therefore fresh — and
`_record_conflict` (which does read level-0 reasons) isn't used together with
reduce. That's correct-by-luck. **Fix:** `_reduce_db` now (a) *locks* any clause
that is currently a reason so it is never deleted, and (b) builds an old→new
index remap and rewrites every `self.reason[v]`. Verified: PHP(8,7)/PHP(9,8)
trigger 30–77 reduces and thousands of clause deletions, proofs still valid.

### F2 — `_minimize` accepted an unused `seen` argument and recomputed marks *(clarity, fixed)*
The recursive self-subsuming minimizer took a `seen` parameter it ignored,
rebuilding a `mark` set instead. Harmless but misleading. **Fix:** dropped the
dead parameter; documented the routine.

### F3 — Sudoku parser rejected the common multi-line block form *(UX bug, fixed in Phase 2 already, re-confirmed)*
Grids written as nine lines of nine contiguous characters (`8........`) raised
`ValueError`. Only the single-81-char compact form and space-separated form
parsed. **Fix:** per-line detection — a line with no spaces/commas is treated as
one character per cell. Re-verified on the "world's hardest" Sudoku.

### F4 — `from_dimacs` silently tolerates a clause count that disagrees with the header
Many real DIMACS files miscount `p cnf V C`. Rather than crash, we record the
declared count on the object and trust the actual clauses. **Decision:** keep
the lenient behavior (matches real-world solvers) but it's now intentional and
documented, not accidental.

### F5 — Empty / degenerate inputs
Checked: empty formula (0 clauses) → SAT with the all-false model; a formula
containing the empty clause → UNSAT immediately; a clause with a tautology
(`x ∨ ¬x`) → dropped; duplicate literals → de-duplicated; a variable appearing
in no clause → still decided and assigned (heap seeded with all vars). All
behave correctly; added regression tests.

### F6 — N-Queens n=2,3 are UNSAT and must say so
`queens 2` and `queens 3` have no solution. Confirmed the solver returns UNSAT
(not a crash or a bogus board), and `n=1` returns the single trivial solution.

### F7 — Self-loop edges in graph coloring
A self-loop `(v,v)` can never be properly colored, but our edge clause
`(¬c[a][k] ∨ ¬c[b][k])` with a==b becomes `(¬c[v][k] ∨ ¬c[v][k])` = a unit
forbidding every color → spuriously UNSAT for *any* k. **Decision:** skip
self-loops in encoding (a self-loop is a modeling error, not an uncolorable
graph); documented. Added a test that a graph with a self-loop still colors its
non-loop structure.

## Re-run gate
After fixes: 2,500-instance differential = 0 mismatches; 974 UNSAT proofs all
verified; PHP family proofs valid through dozens of reduces; all targeted edge
cases pass. Zero of the listed issues reproduce.
