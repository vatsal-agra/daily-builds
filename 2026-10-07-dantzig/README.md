# Dantzig — a certifying LP / MIP solver

Dantzig solves **linear and mixed-integer programs** and **proves its answers**. It is written from scratch in Go (standard library only, about 6,000 lines plus 2,200 lines of tests). The float simplex and branch & bound find the answer. A tiny, separate checker then re-verifies it in **exact rational arithmetic** (`math/big.Rat`). You never have to trust floating point.

```
$ dantzig solve examples/knapsack.lp --proof k.json
status: OPTIMAL (exact certificate verified)
objective (max): 29
$ dantzig check examples/knapsack.lp k.json
VERIFIED: status optimal (checked with exact rational arithmetic)
  proof tree: 5 nodes, 3 leaves (3 bound, 0 Farkas, 0 open, 0 uncertified)
```

## Why this idea works
Commercial solvers answer in floating point and are sometimes wrong. HiGHS reports `945.999999` on one of my big-M test models whose exact optimum is `946`. The trick that keeps an exact checker small is that **weak duality makes every certificate just a vector `y`**. For *any* `y`, the Lagrangian bound

```
Σ_j min_{x_j ∈ box} d_j·x_j  +  Σ_i min_{r_i ∈ range_i} y_i·r_i ,   d = c − Aᵀy
```

is a valid lower bound on the LP. So the checker (`internal/exact`, about 150 lines of rational arithmetic) knows nothing about simplex, bases or tableaux:

| Claim | Certificate | Checker proves |
|---|---|---|
| LP optimal | primal `x`, dual `y` | `x` feasible and bound(`y`) = `c·x` |
| LP infeasible | Farkas `y` | bound of `y` for the zero objective is > 0 |
| LP unbounded | feasible point + ray | the ray is admissible and improving |
| MIP optimal / infeasible | incumbent + **proof tree** | the splits partition the integer box, and every leaf is a Farkas vector, a gcd argument or a bound ≥ the incumbent |
| MIP unbounded | integer point + integral ray | `x₀ + t·ray` stays integer-feasible and improves forever |

## Run it
```
go build -o dantzig ./cmd/dantzig

dantzig solve  model.lp [--proof p.json] [--time S] [--nodes N] [--branch pseudo|mostfrac] [--no-dive] [--no-proof] [--log] [--quiet] [--values all]
dantzig check  model.lp p.json        # independent exact re-verification (exit 3 if rejected)
dantzig sens   model.lp               # exact shadow prices, reduced costs, ranging
dantzig report model.lp out.html      # self-contained HTML report
dantzig gen    list                   # knapsack setcover assignment tsp sudoku facility transport diet
dantzig fmt    model.lp               # canonical form
dantzig export model.lp               # float JSON for other solvers
```
Exit codes: `solve` returns 0 for optimal, 10 for infeasible or unbounded, and 20 for a limit or unknown result. `check` returns 3 for a rejected proof.

Model format (CPLEX-flavoured, exact numbers: decimals, fractions, `1e3`):
```
Maximize
 profit: 40 a + 55 b - 120 sa
Subject To
 labor: 3 a + 5 b <= 60
 band:  10 <= a + b <= 20        \ ranges
 gate:  a - 20 sa <= 0
Bounds
 0 <= a <= 20
 b free
Integer
 a b
Binary
 sa
End
```
Run `./demo.sh`, `go test ./...` and `./mutants.sh` to see everything work. `tools/crosscheck.py` compares against HiGHS when scipy is available (`/usr/bin/python3 tools/crosscheck.py --dantzig ./dantzig`).

## Features
1. **LP-format language.** Parser and writer with ranges, bounds, free/integer/binary variables, fractions and constants on either side. Errors show line, column and a caret. A parser fuzzer (30k mutations) guarantees no panics and a stable round trip.
2. **Bounded-variable simplex.** Composite two-phase primal, dual simplex warm starts, Harris ratio test, Bland fallback, periodic refactorisation. Dual stalls are detected and broken with cost perturbation. Handles Beale, Kuhn and Klee–Minty.
3. **Exact certificates** for optimal, infeasible and unbounded LPs.
4. **Certified branch & bound.** Best-bound search with plunging, a proof tree of one dual vector per leaf, and a checker that re-verifies the whole tree. Also gcd (integer-lattice) infeasibility leaves, and a certified UNBOUNDED / INFEASIBLE classification when the relaxation is unbounded. Proofs are a flat node array, so deep trees are fine.
5. **Sensitivity analysis.** Exact shadow prices, reduced costs, cost ranging and RHS ranging. Tests re-solve inside the ranges (the prediction must hold exactly) and just outside them (it must break).
6. **Model generators.** Knapsack, set cover, assignment, TSP (MTZ), sudoku, facility location, transportation and diet, each verified against a brute-force oracle.
7. **Search upgrades.** Pseudocost branching, a two-direction diving heuristic, node and time limits (honoured even inside one LP), a progress log with gap, and partial proofs that still verify a bound when the search stops early.
8. **HTML report.** A convergence chart, the proof tree (collapsed when huge), the solution, sensitivity tables, and the certificate hash. It follows light and dark mode and works at phone width.

## Numbers
Everything below is certified exactly.

- 40-item, 3-constraint knapsack: 470 nodes, 27 ms.
- TSP with 9 cities: 243 proof nodes, under 0.1 s.
- The "hardest" 9×9 sudoku: 2.6 s. Most of that is the dense 324×1053 tableau.
- Klee–Minty n = 14: 30 ms.
- About 2,000 models cross-checked against HiGHS with 0 mismatches.

## Why I built this today
The repo already has a lot of languages, simulators and distributed systems. It has no optimisation solver, and none of its builds *prove* anything. A solver whose answers can be audited by a short exact checker is a satisfying small idea: the hard part (the search) is allowed to be sloppy, and the trusted part is tiny. The adversarial review ([REVIEW.md](REVIEW.md)) found 12 real bugs, including a dual simplex that never terminated on a zero-objective sudoku. The mutation harness then found 7 holes in my own tests.

## Layout
```
cmd/dantzig         CLI (+ end-to-end tests)
internal/model      exact model, parser, writer
internal/exact      rational algebra, Lagrangian bound, Farkas / ray / gcd checkers
internal/simplex    float tableau simplex (primal, dual, perturbation)
internal/lp         float -> exact glue, certified LP solve
internal/bb         branch & bound, proof tree, independent checker
internal/sens       exact sensitivity analysis
internal/gen        model generators
internal/report     HTML report
tools/crosscheck.py HiGHS cross-check     demo.sh / mutants.sh   verification scripts
```

## Where a human could take this next
- **Scale.** Sparse LU with Forrest–Tomlin updates, steepest-edge pricing, presolve and scaling. Today it is a dense tableau and practical up to a few hundred rows.
- **Cuts and better search.** Gomory and cover cuts (they need new certificate types), reliability branching, restarts, parallel tree search.
- **Faster exactness.** Certify leaves incrementally with a rational LU, or use p-adic lifting. Today each leaf costs one O(m³) rational solve.
- **Richer certificates.** A VIPR-style interchange format so other tools can check Dantzig's proofs, or so Dantzig can check HiGHS's.
- **Modelling.** Indicator constraints and SOS sets, plus a Python or Go modelling API.
- **Unbounded integer domains.** Lattice-based reasoning (Hermite normal form) so that endless trees like `x − y = 0, x + y − 2z = 1` are decided rather than limited.
