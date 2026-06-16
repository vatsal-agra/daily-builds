# Resolvent

A from-scratch **CDCL SAT solver** in pure Python, with a constraint-modeling
layer, puzzle compilers, an independent UNSAT proof checker, and an interactive
implication-graph visualizer.

> **Status:** Phase 2 (core build) complete — all 4 required features working
> end-to-end: CDCL solver, modeling layer, four puzzle compilers, and
> verification/proof checking. See `PLAN.md`.

Quick taste:
```
python3 -m resolvent.cli demo
python3 -m resolvent.cli sudoku examples/sudoku_hard.txt
python3 -m resolvent.cli queens 20
python3 -m resolvent.cli php 6 5 --check-proof
```

Full README filled in at ship time (Phase 6).
