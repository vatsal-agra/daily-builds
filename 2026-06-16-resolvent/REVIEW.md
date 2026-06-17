# Resolvent — Adversarial Review

I attacked my own solver as a hostile reviewer: weird inputs, trivial cases,
proof soundness, heuristic honesty, and lurking footguns. Findings below, each
with a fix and a re-test.

## Findings

### 1. (BUG, soundness) Trivial / load-time UNSAT emitted an *unverifiable* proof
`Solver(CNF(1,[[1],[-1]]), log_proof=True)` and an explicit empty input clause
both returned UNSAT with `proof == []`. An empty DRUP proof fails `check_proof`
(it never derives the empty clause), so a *correct* UNSAT answer shipped a proof
that an independent checker **rejects** — the worst kind of bug for a tool whose
selling point is "an UNSAT you can trust."
- **Cause:** these conflicts are detected during clause loading / top-level
  propagation, before the main loop's proof-logging path.
- **Fix:** when the formula is decided UNSAT before search (loading conflict or
  level-0 propagation conflict), log the empty clause `[]`. It is RUP by
  construction (the original units propagate to a conflict), so the checker now
  accepts it.
- **Re-test:** both cases now produce `proof == [[]]` and `check_proof` → True.

### 2. (BUG, robustness) `check` crashed on solver-formatted model files
`resolvent check f.cnf model.txt` did `int(t)` on every whitespace token after a
small denylist. A model file containing any unexpected word (e.g. a comment)
raised an unhandled `ValueError` instead of a clean message.
- **Fix:** silently skip any non-integer token; parse only the literals.
- **Re-test:** feeding a full `v ... 0` line plus stray words now parses cleanly.

### 3. (CLEANLINESS) Dead code in the visualizer
`render_html` computed an unused `on_cut` variable and had a `_lit_label(l) if
False else str(l)` no-op ternary left over from a refactor. Harmless but sloppy.
- **Fix:** removed both; edge labels now just list the clause literals.

### 4. (LATENT, defensive) Conflict-analysis trail walk could negative-index
`analyze()` walks the trail backward with `while not seen[abs(trail[index])]`.
The loop is safe *by invariant* (when `decision_level >= 1` the conflict clause
always contains ≥1 current-level literal, so `counter > 0` and a seen literal
exists before `index` reaches 0). But a future change to that invariant would
silently wrap to `trail[-1]` instead of failing loudly.
- **Fix:** added an explicit `assert index >= 0` guard so any invariant
  violation is caught immediately rather than corrupting the learned clause.

### 5. (HONESTY) "Each heuristic changes behavior" — measured, with a caveat
Comparing configs on a 140-var random instance at ratio 4.3:
`full` 3015 conflicts; `no-vsids` 20443 (≈7× worse); `no-restarts` 1654;
`no-reduce` 1875. VSIDS is unambiguously load-bearing. **Restarts and DB
reduction were *not* always a win on a single instance** (this seed solves
faster without restarts). That is expected — they pay off in aggregate and on
harder instances, not on every formula. The mechanisms demonstrably *fire*
(14 restarts, clauses deleted under `bench`), and I'm not claiming a universal
speedup. Noted here rather than cherry-picking a flattering seed.

### 6. (CHECKED, no change) Things I tried to break but couldn't
- Empty formula `p cnf 0 0` → SAT (correct). Tautology `(x ∨ ¬x)` and duplicate
  literals → handled by load-time simplification; oracle agrees.
- Watched-literal invariant: binary clauses, clause migration between watch
  lists, and conflict truncation all verified against the brute-force oracle on
  2000+ random instances with **zero** verdict mismatches and zero bad models.
- 15 independently-found random UNSAT instances: every DRUP proof verified by
  the RUP checker.
- DIMACS parser: missing header, non-integer tokens, missing terminating `0`,
  and a bad `p` line all produce positioned, human-readable errors.

## Gate
A fresh run of `python3 -m resolvent demo` and the test suite hits **none** of
the bugs above after the fixes.
