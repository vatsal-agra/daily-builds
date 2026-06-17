# Resolvent — Adversarial Review

I attacked the solver as a hostile reviewer trying to make it return a wrong
answer (wrong SAT/UNSAT verdict, or a "model" that doesn't satisfy the formula).
SAT solvers are notorious for bugs that only surface under heavy search, so the
primary weapon was **differential testing**: run thousands of random formulas
through the CDCL solver and two independent oracles (exhaustive truth-table and
a textbook recursive DPLL), and flag any disagreement or any invalid model.

## Issues found and fixed

### 1. (CRITICAL) VSIDS heap could orphan variables → false SAT
**Symptom:** small formulas (≤7 vars) were always correct, but at 8–13 vars the
solver frequently returned `SATISFIABLE` with a model that *failed* its own
clauses (77 invalid models / 400 instances).

**Root cause:** the lazy VSIDS heap pushed a fresh `(−activity, var)` entry only
when a variable was bumped *while unassigned*. But conflict analysis bumps
variables that are currently *assigned* (they're on the trail). For such a
variable, its activity changed but its sole heap entry became stale. An
`in_heap` flag then suppressed re-pushing it on backtrack, because a (stale)
entry technically still existed. Result: the variable was never returned by
`pick_branch` and never re-pushed — it stayed permanently unassigned. When the
heap ran dry of *valid* entries, `pick_branch` returned `None`, so the solver
concluded "all variables assigned ⇒ SAT" while a clause was actually violated.

**Fix:** dropped the `in_heap` flag and established a clean invariant — *every
unassigned variable always has at least one heap entry matching its current
activity*. Maintained by (a) pushing a variable whenever it becomes unassigned
during backtrack, (b) pushing on bump when unassigned, and (c) refreshing all
unassigned variables when activities are rescaled. `pick_branch` now only ever
returns `None` when there is genuinely no unassigned variable. After the fix:
**0 mismatches and 0 invalid models across 3,800 then 6,000 random instances.**
(`resolvent/solver.py`, `_heap_push/_heap_pop_max/_bump_var/_backtrack`.)

### 2. (MINOR) Confusing parser error location
`p cnf` with a variable index exceeding the declared count raised
`DimacsError(line 0, …)` because the check ran after the parse loop with no line
recorded. Now the parser remembers the line where the offending maximum variable
appeared and reports it. (`resolvent/cnf.py`.)

## Things I tried to break but couldn't (all correct)
- **Empty formula** (0 vars / 0 clauses) → SAT with empty model. ✓
- **Empty clause** present in input → immediately UNSAT. ✓
- **Unit clauses** at the root, including contradictory `x` ∧ ¬`x` → UNSAT. ✓
- **Tautological clauses** (`x ∨ ¬x`) are dropped at construction without
  affecting satisfiability. ✓
- **Duplicate literals** in a clause are de-duplicated. ✓
- **Variables declared but unused** still appear in the model. ✓
- **Clause-DB reduction** never deletes a locked (reason) clause and only ever
  removes *learned* (redundant) clauses, so it can't change a verdict. ✓
- **Determinism:** same formula + seed ⇒ byte-identical model and statistics
  across repeated runs. ✓
- **Parser robustness:** missing header, multi-line clauses, missing terminating
  `0`, and non-integer tokens are all handled (the latter two: tolerated and
  rejected respectively, with line numbers). ✓
- **Independent oracle agreement:** verdicts matched the recursive-DPLL oracle on
  1,500 instances up to 16 variables, and the exhaustive truth-table oracle on
  6,000 instances up to 11 variables. ✓
- **Pigeonhole** PHP(n+1→n) is correctly UNSAT with the expected exponential
  conflict growth. ✓

## Gate
A fresh run-through (`python3 -m resolvent fuzz --n 6000 --seed 123 --maxvars
11`) hits zero of the listed issues: solver agrees with the oracle on every
instance and every reported model satisfies its formula.
