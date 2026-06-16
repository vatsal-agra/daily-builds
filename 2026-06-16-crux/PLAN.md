# Crux — a from-scratch CDCL SAT solver

## Concept
**Crux** is a modern Boolean satisfiability (SAT) solver written from scratch in
pure Python, plus the tooling that makes a solver actually useful: problem
*encoders* that turn real puzzles (Sudoku, graph colouring, N-Queens, pigeonhole)
into CNF, a *verified* result pipeline (every SAT model is checked against the
formula; every small instance is cross-checked against brute force), and an
interactive single-file HTML *visualizer* that shows the heart of the algorithm —
the implication graph, the conflict, the 1-UIP cut and the clause it learns.

The core is not toy DPLL. It is **CDCL** (Conflict-Driven Clause Learning), the
algorithm behind every competitive SAT solver since Chaff/MiniSat:

- **Two-watched-literals** unit propagation (the data structure that makes BCP fast).
- **1-UIP conflict analysis** producing an asserting learned clause.
- **Non-chronological backjumping** to the right decision level.
- **VSIDS** activity-based decision heuristic with decay.
- **Phase saving** (a.k.a. progress saving).
- **Luby-sequence restarts** and **activity-based learned-clause deletion**.

## Why it's interesting
SAT is the canonical NP-complete problem; a CDCL solver is a small piece of code
that does something genuinely deep — it learns from its own mistakes, and the
clauses it derives are *resolution proofs*. Watched literals and 1-UIP are
beautiful, fiddly, and easy to get subtly wrong, which makes them a perfect
target for adversarial review and differential testing. And because SAT is a
universal substrate, a working solver immediately solves a zoo of unrelated
puzzles through encoding alone — which is a very satisfying payoff to visualize.

## Architecture
```
crux/
  cnf.py        Literal/clause representation, CNF model, DIMACS parse + write
  solver.py     CDCL engine: trail, watched literals, BCP, VSIDS, analyze, restarts
  brute.py      Reference exhaustive solver + model checker (the oracle)
  encoders.py   Sudoku / graph-colouring / N-Queens / pigeonhole  <-> CNF
  proof.py      DRAT-style proof logging for UNSAT + a forward (RUP) checker
  viz.py        Generates the self-contained HTML conflict-analysis visualizer
  cli.py        `solve / check / gen / encode / decode / proof / viz / demo`
__main__.py     Entry point so `python -m crux ...` works
tests/          unittest suite + demo.sh
web/            generated visualizer output lands here
```

Data flow: `DIMACS or encoder -> CNF -> Solver -> (SAT model | UNSAT [+proof]) ->
checker verifies -> decoder renders puzzle solution / viz renders the search`.

## Feature list

### Required (core)
1. **CDCL engine** — full conflict-driven clause learning with two-watched-literals
   BCP, 1-UIP analysis, non-chronological backjumping, VSIDS + decay, phase saving,
   Luby restarts, and activity-based clause deletion. Reports SAT/UNSAT with a
   model and search statistics (decisions, conflicts, propagations, learned, restarts).
2. **DIMACS I/O + verified models** — parse standard DIMACS CNF (comments, `p cnf`,
   clause-per-line tolerant of whitespace), and a `check` that validates any SAT
   model satisfies every clause. Errors are reported with line context.
3. **Differential correctness oracle** — an independent brute-force solver and a
   randomized fuzzer that compares Crux against it on thousands of small random
   formulas: SAT/UNSAT verdict must match, and every claimed model must check out.
4. **Problem encoders + decoders** — Sudoku, graph k-colouring, N-Queens, and
   pigeonhole, each encoded to CNF (with an efficient at-most-one encoding) and
   decoded back into a human-readable solution. These prove the solver solves
   real, hard instances, not just random noise.

### Stretch
5. **Interactive HTML visualizer** — a self-contained page that runs a JS mirror
   of the engine, draws the implication graph as decisions/propagations land,
   highlights the conflict, the 1-UIP cut, and the learned clause, and lets you
   step the search forward/back. No external libraries.
6. **DRAT-style UNSAT proofs** — log learned clauses as a resolution proof and
   ship a forward RUP (reverse unit propagation) checker that independently
   certifies an UNSAT result, so we don't just trust the solver's word.
7. **#SAT model counting** — an exact model counter (DPLL with component-free
   exhaustive counting) for small instances, cross-checked against brute force.

## Definition of done
- 4/4 required + ≥1 stretch fully working end-to-end (targeting all 3 stretch).
- Fuzzer: thousands of random formulas, zero disagreements vs brute force.
- A real 9×9 Sudoku solved from clues and decoded correctly.
- UNSAT pigeonhole instance certified by the independent proof checker.
- Full test suite green + a `demo.sh` that exercises every feature.
