# Resolvent

A from-scratch **CDCL SAT solver** in pure Python — conflict-driven clause
learning, two-watched-literal propagation, VSIDS branching, Luby restarts, a
brute-force differential oracle, problem encoders (Sudoku / N-Queens / graph
coloring / pigeonhole), DRUP UNSAT-proof checking, and an interactive
implication-graph visualizer.

> **Status:** Phase 1 (plan) complete. See [PLAN.md](./PLAN.md) for the concept,
> architecture, and feature list. Build in progress.

## Quick map
- `PLAN.md` — concept, architecture, 7 features (4 required + 3 stretch).
- (coming) `resolvent/` — the engine, encoders, visualizer, CLI.
- (coming) `tests/` — brute-force differential fuzzer + unit tests.
- (coming) `demo.sh` — exercises every feature end-to-end.
