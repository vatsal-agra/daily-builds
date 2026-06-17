# Backjump

A from-scratch **CDCL SAT solver** (conflict-driven clause learning) in pure Python —
with verified UNSAT proofs, real puzzle encoders, and an interactive
implication-graph visualizer.

> **Status: Phase 4 complete — reviewed, hardened, and polished.** All four
> required features plus all three stretch features work end-to-end; the
> adversarial review (see [REVIEW.md](REVIEW.md)) found 7 issues, all fixed.
> Verification suite and final docs next. See [PLAN.md](PLAN.md).

## Quick start
```bash
python3 bj.py demo                 # guided tour of every feature
python3 bj.py queens 30            # solve 30-queens
python3 bj.py sudoku               # solve the built-in hard Sudoku
python3 bj.py pigeon 7 6           # UNSAT, with a verified proof
python3 bj.py color 3 --cycle 5    # 3-colour a 5-cycle
python3 bj.py fuzz --trials 1000   # differential test vs brute force
python3 bj.py phase                # the 3-SAT satisfiability cliff
python3 bj.py viz pigeon --out v.html   # generate the interactive visualizer
```

## What works so far
- **CDCL core** — DIMACS parser, two-watched-literal propagation, 1-UIP clause
  learning, non-chronological backjumping, VSIDS branching, phase saving, Luby
  restarts. Verified correct against brute force on thousands of random instances.
- **Verified answers** — SAT models are checked clause-by-clause; UNSAT answers
  come with a DRUP-style proof that an *independent* RUP checker verifies down to
  the empty clause.
- **Encoders** — Sudoku, N-Queens, graph colouring, pigeonhole → CNF → solve → decode.
- **Visualizer** — a self-contained HTML file that replays a real solve: trail,
  implication graph, 1-UIP conflict cut, learned clauses, VSIDS bars, restarts.

See [PLAN.md](PLAN.md) for the full architecture and feature list.
