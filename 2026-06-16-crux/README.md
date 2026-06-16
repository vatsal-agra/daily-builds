# Crux

A from-scratch **CDCL SAT solver** in pure Python.

> Status: **Phase 1 (PLAN) complete.** See [PLAN.md](PLAN.md) for the full
> concept, architecture, and feature list.

Crux is a modern conflict-driven clause-learning SAT solver (two-watched-literals
BCP, 1-UIP learning, non-chronological backjumping, VSIDS, Luby restarts) plus the
tooling that makes a solver useful: DIMACS I/O, problem encoders (Sudoku, graph
colouring, N-Queens, pigeonhole), a brute-force differential oracle, DRAT-style
UNSAT proofs with an independent checker, exact model counting, and an interactive
HTML visualizer of conflict analysis.

Build phases and how to run will be filled in as each phase lands.
