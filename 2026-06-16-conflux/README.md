# Conflux

A from-scratch **CDCL SAT solver** in pure Python (no dependencies), with an
interactive single-file HTML visualizer of the conflict-driven clause-learning
loop.

> **Status:** Phase 1 (plan) complete. See [PLAN.md](PLAN.md) for the full design.

## What it is (planned)
- A modern SAT solver: two-watched-literal propagation, VSIDS, 1-UIP conflict
  analysis, non-chronological backjumping, restarts, phase saving.
- Certified answers: SAT models are independently verified; UNSAT results carry
  a DRAT proof validated by an independent checker.
- Problem encoders (Sudoku, N-Queens, graph coloring, pigeonhole) that reduce
  real puzzles to CNF and decode solutions back.
- An interactive HTML visualizer that animates the search.

Build in progress — this README is updated at the end of every phase.
