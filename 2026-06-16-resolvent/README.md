# Resolvent

A from-scratch **CDCL SAT solver** in pure Python, with a constraint-modeling
layer, puzzle compilers, an independent UNSAT proof checker, and an interactive
implication-graph visualizer.

> **Status:** Phase 3 (adversarial review) complete — 7 findings fixed,
> incl. a `reduceDB` clause-reindexing landmine. 2,500-instance differential is
> clean and 974 UNSAT proofs verify. See `REVIEW.md`.

Quick taste:
```
python3 -m resolvent.cli demo
python3 -m resolvent.cli sudoku examples/sudoku_hard.txt
python3 -m resolvent.cli queens 20
python3 -m resolvent.cli php 6 5 --check-proof
```

Full README filled in at ship time (Phase 6).
