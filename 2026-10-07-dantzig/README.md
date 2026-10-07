# Dantzig

A **certifying LP / MIP solver** in Go (standard library only). It solves linear and
mixed-integer programs with a bounded-variable primal + dual simplex and branch & bound,
and every answer ships with an **exact rational certificate** that an independent checker
verifies with `math/big.Rat`.

> Status: **Phase 5 complete** (58 test functions, 37-assertion `demo.sh`, 17/17 mutants killed). Earlier: **Phase 4 complete** (stretch features: sensitivity analysis, generators with brute-force oracles, search upgrades, HTML report). Previously: **Phase 3 complete** (4 required features built; adversarial review done, 12 findings fixed — see [REVIEW.md](REVIEW.md)). Sections below grow
> with each phase; see [PLAN.md](PLAN.md) for the full plan.

## Quick start
```
go build -o dantzig ./cmd/dantzig
./dantzig solve examples/knapsack.lp --proof knapsack.proof.json
./dantzig check examples/knapsack.lp knapsack.proof.json
./dantzig gen tsp 8 3 > tsp.lp && ./dantzig solve tsp.lp
```

## Done so far
1. LP-format language (parser + writer, ranges, bounds, free/int/binary, fractions) with positioned errors
2. Bounded-variable simplex: composite two-phase primal, dual simplex warm starts, cost perturbation on dual stalls
3. Exact certificates: optimal (primal + dual), infeasible (Farkas), unbounded (ray)
4. Branch & bound with a proof tree; `dantzig check` re-verifies the entire proof exactly

## Review highlights (phase 3)
- Dual-degenerate LPs (e.g. a zero-objective sudoku) used to loop forever: fixed with stall detection + cost perturbation.
- Proofs are now a flat node array with an iterative checker (deep trees broke the JSON decoder).
- New certificates: integer-lattice (`gcd`) infeasibility, and certified UNBOUNDED / INFEASIBLE classification of MIPs whose LP relaxation is unbounded.
- `tools/crosscheck.py` compares against HiGHS: ~2,000 models, 0 mismatches.

## Stretch features added (phase 4)
- `dantzig sens model.lp` — exact shadow prices, reduced costs, cost ranging and RHS ranging (validated by re-solving inside the ranges)
- `dantzig gen <kind>` — knapsack, set cover, assignment, TSP (MTZ), sudoku, facility location, transportation, diet; each checked against a brute-force oracle
- Search upgrades: pseudocost branching, two-direction diving heuristic, node/time limits, progress log with gap (`--log`)
- `dantzig report model.lp out.html` — self-contained HTML report (convergence chart, proof tree, solution, sensitivity, certificate)

## Verification (phase 5)
- `go test ./...` — 58 test functions across 8 packages (random-vs-brute-force, primal-vs-dual, tamper tests, parser fuzz, CLI end-to-end)
- `./demo.sh` — 37 assertions exercising every feature through the CLI
- `./mutants.sh` — plants 17 bugs (in the checker, bounds, simplex, parser, sensitivity, generators); every one is killed. The first run left 7 alive, which exposed real test gaps; they were closed.
