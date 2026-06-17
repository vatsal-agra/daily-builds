# Resolvent

A from-scratch **CDCL SAT solver** in pure Python (no dependencies).

> Build status: Phase 4 complete — all required + 3 stretch features in.

## Quick start
```bash
python3 -m resolvent demo                       # guided tour of every feature
python3 -m resolvent solve examples/sat_simple.cnf
python3 -m resolvent decode sudoku              # solve the built-in puzzle
python3 -m resolvent decode queens 12           # 12-Queens
python3 -m resolvent decode coloring petersen 3 # 3-color the Petersen graph
python3 -m resolvent verify examples/unsat_simple.cnf   # UNSAT + checked proof
python3 -m resolvent viz examples/unsat_simple.cnf out.html
python3 -m resolvent fuzz --n 1000              # differential test vs an oracle
```

## Features
**Core (required)**
- **DIMACS CNF front-end** — strict parser + writer.
- **CDCL solver** — two-watched-literal propagation, 1-UIP conflict analysis
  with clause learning, non-chronological backjumping, self-subsuming clause
  minimization.
- **Heuristics** — VSIDS branching, phase saving, Luby restarts, learned-clause
  database reduction.
- **`solve` CLI** — SAT/UNSAT, a self-verified model, and full statistics.

**Stretch**
- **Problem encoders** — Sudoku, graph k-coloring, N-Queens, pigeonhole, all
  compiled to CNF and decoded back to readable solutions.
- **Independent proof checking** — UNSAT proofs verified by a separate RUP
  checker that shares no search logic with the solver; plus a differential
  fuzzer against an exhaustive oracle.
- **Implication-graph visualizer** — standalone HTML/SVG of the first conflict,
  with decisions, implications, the 1-UIP cut, and the learned clause.

See [PLAN.md](PLAN.md) and [REVIEW.md](REVIEW.md).
