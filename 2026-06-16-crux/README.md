# Crux

A from-scratch **CDCL SAT solver** in pure Python.

> Status: **Phase 3 (ADVERSARIAL REVIEW) complete.** Six findings fixed (incl. a
> 1883× VSIDS heap blow-up and a dead, misleading `rng_seed` param); see
> [REVIEW.md](REVIEW.md). Engine re-fuzzed clean. See [PLAN.md](PLAN.md) for the
> concept and feature list.

### Output conventions
`crux solve` follows the SAT-competition format: `s SATISFIABLE` / `s UNSATISFIABLE`
/ `s UNKNOWN`, a `v <literals> 0` model line when SAT, and exit codes **10** (SAT),
**20** (UNSAT), **0** (UNKNOWN). The `--max-conflicts N` budget bounds the search.

## Try it (current)
```bash
# solve a random instance
python3 -m crux gen --vars 30 --clauses 120 --seed 1 | python3 -m crux solve

# solve a real 9x9 Sudoku and print the grid
python3 -m crux decode sudoku examples/sudoku_hard.txt

# 8-queens, graph colouring, pigeonhole (UNSAT)
python3 -m crux decode queens -n 8
python3 -m crux encode pigeonhole -m 6 -n 5 | python3 -m crux solve

# prove the engine correct against brute force
python3 -m crux fuzz --trials 2000
```

### What works now
- **CDCL engine** — two-watched-literals BCP, 1-UIP learning, non-chronological
  backjumping, VSIDS + decay, phase saving, Luby restarts, clause deletion, clause
  minimization. Reports a verified model and full search statistics.
- **DIMACS I/O + model checking** — tolerant parser, `check` verifies any model.
- **Differential oracle** — `fuzz` cross-checks Crux vs an exhaustive brute solver
  (2000+ random formulas, zero disagreements; every model re-verified).
- **Encoders/decoders** — Sudoku, graph k-colouring, N-Queens, pigeonhole, with
  an efficient Sinz sequential at-most-one encoding.

Crux is a modern conflict-driven clause-learning SAT solver (two-watched-literals
BCP, 1-UIP learning, non-chronological backjumping, VSIDS, Luby restarts) plus the
tooling that makes a solver useful: DIMACS I/O, problem encoders (Sudoku, graph
colouring, N-Queens, pigeonhole), a brute-force differential oracle, DRAT-style
UNSAT proofs with an independent checker, exact model counting, and an interactive
HTML visualizer of conflict analysis.

Build phases and how to run will be filled in as each phase lands.
