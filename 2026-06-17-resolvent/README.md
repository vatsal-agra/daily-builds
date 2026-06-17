# Resolvent

A from-scratch **CDCL SAT solver** in pure Python (no dependencies).

> Build status: Phase 2 complete — core solver works. See [PLAN.md](PLAN.md).

## Quick start
```bash
python3 -m resolvent solve examples/sat_simple.cnf
python3 -m resolvent solve examples/unsat_simple.cnf
python3 -m resolvent fuzz --n 1000 --seed 0
```

## What works so far
- **DIMACS CNF front-end** — strict parser + writer (`resolvent/cnf.py`).
- **CDCL core** — two-watched-literal propagation, 1-UIP conflict analysis with
  clause learning, non-chronological backjumping (`resolvent/solver.py`).
- **Heuristics** — VSIDS branching with decay, phase saving, Luby restarts,
  learned-clause DB reduction.
- **`solve` CLI** — SAT/UNSAT verdict, model (self-verified against the original
  clauses), and full search statistics.
- **`fuzz`** — differential testing against an exhaustive truth-table oracle.

Stretch features (encoders, independent proof checking, implication-graph
visualizer) are in progress.
