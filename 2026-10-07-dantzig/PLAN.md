# Dantzig — a certifying LP / MIP solver (PLAN)

## Concept
Dantzig is a from-scratch **linear and mixed-integer programming solver** written in Go
(standard library only). You describe a model in a CPLEX-flavoured text format, it solves
it with a bounded-variable **primal + dual simplex** and **branch & bound**, and — the
distinctive part — it never asks you to trust floating point: every answer ships with an
**exact rational certificate** that a separate, tiny checker verifies using `math/big.Rat`.

* optimal LP        → primal solution + dual vector `y`; checker proves `primal obj == Lagrangian bound`
* infeasible        → Farkas vector `y`; checker proves `bound(y) > 0` on the empty objective
* unbounded         → feasible point + improving ray; checker proves the ray is admissible
* MIP optimal       → incumbent + a **proof tree** (every branch split + one dual vector per leaf);
                      checker proves the leaves partition the integer box and every leaf's
                      Lagrangian bound is >= the incumbent (no better solution exists)

## Why it is interesting
Industrial solvers (CPLEX, Gurobi, HiGHS) answer in floating point and are occasionally wrong
(research on "exact MIP" – SCIP-exact, VIPR certificates – exists because of this). The key
insight that keeps this build small: **weak duality makes every certificate "just a vector y"**.
For *any* y the Lagrangian bound `sum_j min_{x_j in box}(d_j x_j) + sum_i min_{r_i in range}(y_i r_i)`
with `d = c - A^T y` is a valid lower bound. So the checker needs no knowledge of simplex,
bases or tableaux — it is ~150 lines of exact arithmetic that is trivially auditable, while the
solver itself can be as clever / as sloppy-in-floating-point as it likes.

## Architecture
```
cmd/dantzig            CLI: solve | check | sens | gen | fmt | report
internal/model         Model type (exact Rat data), LP-format parser + writer
internal/exact         rational linear algebra, Lagrangian bound, KKT / Farkas / ray checkers
internal/simplex       float dense-tableau bounded simplex: two-phase primal, dual (warm start),
                       Harris-style ratio test, Bland fallback, periodic refactorisation
internal/bb            branch & bound: best-bound + plunging, pseudocost branching, diving
                       heuristic, exact leaf certification, proof tree emit + independent check
internal/sens          exact sensitivity analysis (shadow prices, reduced costs, ranging)
internal/gen           model generators (knapsack, set cover, assignment, TSP/MTZ, sudoku, facility)
internal/report        self-contained HTML report (tree SVG, bound/incumbent convergence chart)
```
Computational form: every row gets a *logical* variable, `[A | -I] [x; r] = 0`, `r in [rl, ru]`,
so rows (<=, >=, =, ranges) and variable bounds are uniform and the slack basis is trivial.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | LP-format language: parser/writer (ranges, bounds, free vars, int/binary, fractions, max/min, constants) with positioned errors | **required** |
| 2 | Bounded-variable simplex: two-phase primal (composite infeasibility phase 1) + dual simplex for warm starts; degeneracy handling | **required** |
| 3 | Exact rational certificates + independent checker for optimal / infeasible / unbounded LP | **required** |
| 4 | Branch & bound MIP with certified proof tree and `check` command that re-verifies the whole proof exactly | **required** |
| 5 | Exact sensitivity analysis: shadow prices, reduced costs, cost & RHS ranging (validated by re-solving) | stretch |
| 6 | Model generators with brute-force oracles (knapsack, set cover, assignment, TSP-MTZ, sudoku, facility) | stretch |
| 7 | Search upgrades: pseudocost branching, diving heuristic, node/time limits, gap reporting | stretch |
| 8 | HTML report: proof tree + convergence chart | stretch |

## Definition of done
All required features end-to-end with exact certificates; adversarial REVIEW.md with fixes;
>= 1 stretch (target: 5-8); tests + `demo.sh` green; README + LEDGER entry.
