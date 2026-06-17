# Resolvent — PLAN

## Concept
**Resolvent** is a from-scratch **CDCL SAT solver** (Conflict-Driven Clause
Learning) written in pure Python stdlib, wrapped in a high-level constraint
modeling layer, a set of real-world puzzle compilers, an **independent UNSAT
proof checker**, and an interactive single-file HTML visualizer of the
solver's implication graph.

Boolean satisfiability is the canonical NP-complete problem. A modern CDCL
solver is one of the most beautiful pieces of practical algorithm engineering
in existence: it takes a problem with `2^n` possible assignments and routinely
slays instances with hundreds of thousands of variables, by *learning from its
own mistakes*. Every conflict it hits is analyzed, distilled into a new clause
that forbids the entire family of failures that led there, and used to jump
back over huge swaths of the search tree.

## Why it's interesting
- The core trio — **two-watched-literal unit propagation**, **1-UIP conflict
  analysis with clause learning**, and **non-chronological backjumping** — is
  subtle to get exactly right, and wrong implementations *look* like they work
  until they silently return a wrong answer. That makes it a perfect
  adversarial-review target.
- It's not a toy: with VSIDS branching, Luby restarts, phase saving, and
  clause-database reduction it's the real architecture used by MiniSat /
  Glucose-class solvers.
- A SAT solver is a *universal* problem solver. The modeling layer + puzzle
  compilers turn Sudoku, N-Queens, graph coloring, and the pigeonhole
  principle into CNF, solve them, and decode the answer back — one engine,
  many problems.
- UNSAT answers are checkable: a separate **DRAT-style proof emitter +
  reverse-unit-propagation checker** independently re-derives the empty clause,
  so the solver doesn't have to be trusted.

## Architecture
```
DIMACS / DSL  ─┐
Puzzle input ──┼─► CNF (Clause DB) ─► CDCL Solver ─► SAT model  ─► decode/verify
               │                          │                    └─► HTML viz
               └─► Tseitin + cardinality  └─► UNSAT + DRAT proof ─► RUP checker
```

Modules (`resolvent/`):
- `cnf.py`    — CNF/clause representation, DIMACS read/write, model checking.
- `solver.py` — the CDCL engine (watched literals, VSIDS, 1-UIP, restarts,
  reduceDB, phase saving) + statistics + DRAT proof logging.
- `model.py`  — modeling DSL: fresh vars, Tseitin encoding of AND/OR/NOT/XOR/
  IMPLIES/IFF, and cardinality constraints (at-least/at-most/exactly-one,
  at-most-k via sequential counter).
- `proof.py`  — independent RUP/DRAT UNSAT proof checker + brute-force oracle.
- `puzzles/`  — sudoku, nqueens, coloring, pigeonhole compilers + decoders.
- `viz.py`    — self-contained HTML implication-graph + decision-trail report.
- `cli.py`    — `solve / sudoku / queens / color / php / gen / verify / viz / demo`.

## Feature list

### Required
1. **CDCL solver core** — two-watched-literal BCP, VSIDS decision heuristic,
   1-UIP conflict analysis + clause learning, non-chronological backjump, Luby
   restarts, phase saving, clause-DB reduction. Reads/writes DIMACS, returns a
   model or UNSAT.
2. **Constraint modeling layer** — a DSL that compiles boolean expressions to
   CNF via Tseitin transformation (AND/OR/NOT/XOR/IMPLIES/IFF) plus cardinality
   constraints (exactly-one, at-most-one, at-most-k sequential-counter encoding).
3. **Puzzle compilers** — Sudoku (any N²×N²), N-Queens, graph K-coloring, and
   pigeonhole, each encoding to CNF through the DSL and decoding the model back
   into a human-readable solution.
4. **Verification & certificates** — every SAT model is checked against the
   clause set; UNSAT is cross-checked against a brute-force oracle on small
   instances; the pigeonhole principle is proven UNSAT; a `verify` command
   validates external model files against a CNF.

### Stretch
5. **DRAT-style proof + independent RUP checker** — the solver emits its learned
   clauses as a proof; a *separate* checker re-validates that every step is a
   reverse-unit-propagation consequence, independently certifying UNSAT.
6. **Interactive HTML visualizer** — a single self-contained file showing the
   implication graph of a conflict, the decision trail, learned clauses, and
   live solver statistics, with hover/inspect — no dependencies, no Graphviz.
7. **(extra) Random k-SAT generator + #SAT model counter** — generate instances
   at the hard phase-transition ratio; an exact DPLL model counter for small
   instances, cross-checked against brute force.

## Verification plan
- Differential: every reported SAT model re-checked against original clauses.
- Oracle: brute force over all `2^n` assignments for small n agrees with the
  solver on SAT/UNSAT and (with the counter) on the exact model count.
- Known-answer: PHP(n+1,n) is UNSAT for all n; N-Queens has the known solution
  counts; a hand 9×9 Sudoku decodes to a valid grid.
- Proof: emitted DRAT proofs pass the independent RUP checker; tampered proofs
  are rejected.
- A `demo.sh` exercises every command end-to-end and a `tests/` unittest suite
  must be fully green.
