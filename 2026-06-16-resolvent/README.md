# Resolvent

A from-scratch **CDCL SAT solver** in pure Python — conflict-driven clause
learning, two-watched-literal propagation, VSIDS branching, Luby restarts, a
brute-force differential oracle, problem encoders (Sudoku / N-Queens / graph
coloring / pigeonhole), DRUP UNSAT-proof checking, and an interactive
implication-graph visualizer.

> **Status:** Phase 2 (core build) complete — CDCL engine, encoders, DRUP proofs
> and the visualizer all run end-to-end. See [PLAN.md](./PLAN.md) for the design.
> Adversarial review, polish, tests and final docs follow.

## Try it
```bash
python3 -m resolvent demo                       # full end-to-end tour
python3 -m resolvent fuzz -n 2000               # differential test vs brute force
python3 -m resolvent solve-puzzle queens --n 8  # encode -> solve -> decode
python3 -m resolvent solve-puzzle sudoku        # solve a hard Sudoku
python3 -m resolvent solve-puzzle pigeonhole --holes 4 --proof php.drup
python3 -m resolvent proofcheck php.cnf php.drup
python3 -m resolvent viz random.cnf --out impl.html
```

## Quick map
- `PLAN.md` — concept, architecture, 7 features (4 required + 3 stretch).
- `resolvent/` — `cnf` (DIMACS), `solver` (CDCL), `oracle` (brute force),
  `generate`, `encoders`, `proof` (DRUP checker), `viz`, `cli`, `demo`.
- (coming) `tests/` — brute-force differential fuzzer + unit tests.
- (coming) `demo.sh` — exercises every feature end-to-end.
