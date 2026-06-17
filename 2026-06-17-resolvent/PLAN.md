# Resolvent — Plan

## Concept
**Resolvent** is a from-scratch **CDCL SAT solver** (Conflict-Driven Clause
Learning) written in pure Python with no dependencies — the same algorithm
family that powers modern hardware verification, program analysis, AI planning,
and theorem proving.

It takes a Boolean formula in CNF (Conjunctive Normal Form) and decides whether
there is an assignment of true/false to its variables that makes every clause
true. SAT is the canonical NP-complete problem, so a real CDCL solver is a
surprisingly small amount of code wrapped around several genuinely clever ideas:
two-watched-literal unit propagation, 1-UIP conflict analysis, non-chronological
backjumping, VSIDS activity-based branching, and Luby restarts.

## Why it's interesting
- It's a *general reasoning engine*: encode Sudoku, graph coloring, N-Queens, or
  the pigeonhole principle into CNF and the same solver cracks all of them.
- The algorithms are subtle and famously easy to get subtly wrong — perfect for
  the adversarial-review gate. We pin correctness down hard with **differential
  testing** against an exhaustive truth-table oracle, and we make UNSAT answers
  *independently checkable* by emitting a resolution/RUP proof and checking it
  with a separate verifier that shares no code with the solver.
- It's distinct from every prior daily build (world-gen, regex, SQL db, Raft,
  physics, autodiff).

## Architecture
```
DIMACS text ──▶ cnf.py (parse/write CNF)
                   │
                   ▼
              solver.py  ── CDCL core
                 ├─ two-watched-literal propagation
                 ├─ 1-UIP conflict analysis + clause learning
                 ├─ non-chronological backjumping
                 ├─ VSIDS branching + phase saving
                 ├─ Luby restarts + clause-DB reduction
                 └─ optional DRAT/RUP proof trace
                   │
        ┌──────────┼─────────────┬──────────────┐
        ▼          ▼             ▼              ▼
  encoders.py   proof.py    bruteforce.py     viz.py
  (problems     (independent (exhaustive      (implication-
   → CNF →       RUP UNSAT    oracle for       graph HTML)
   decode)       checker)     differential)
                   │
                   ▼
                 cli.py  (solve / encode / verify / fuzz / viz / demo)
```

## Feature list

### Required
1. **DIMACS CNF front-end** — strict parser (comments, `p cnf`, clause
   terminators, tautology/empty handling) + writer; round-trips.
2. **CDCL core** — two-watched-literal unit propagation, 1-UIP conflict
   analysis with clause learning, non-chronological backjumping. Returns a
   satisfying model or UNSAT.
3. **Search heuristics** — VSIDS variable activity with decay + phase saving
   (polarity caching), Luby-sequence restarts, and activity-based learned-clause
   database reduction.
4. **Solve CLI + self-verification** — `solve` a DIMACS file, report
   SAT/UNSAT, the model, and statistics (decisions, conflicts, propagations,
   learned clauses, restarts); every SAT model is checked against the original
   clauses before being trusted.

### Stretch
5. **Problem encoders** — Sudoku (9×9), graph k-coloring, N-Queens, and
   pigeonhole PHP(n) compiled to CNF, with solution decoding back to the
   human-readable problem. Pretty-prints solved boards.
6. **Independent proof checking + differential fuzzer** — solver emits a
   clausal (DRAT-style) proof on UNSAT; a separate RUP checker (no shared logic)
   verifies the empty clause is derivable. A fuzzer generates random 3-CNF and
   cross-checks every verdict against an exhaustive truth-table oracle.
7. **Implication-graph visualizer** — generate a standalone HTML/SVG view of
   the implication graph at a captured conflict (decision levels, reason edges,
   the conflicting clause, and the learned 1-UIP cut).

## Verification plan
- Unit tests for parser round-trip, propagation, and known SAT/UNSAT instances.
- Differential test: hundreds of random small formulas, solver verdict ==
  exhaustive oracle verdict; every SAT model satisfies its formula.
- Pigeonhole PHP(n+1→n) is UNSAT and its emitted proof checks out.
- Sudoku: solve real puzzles, decoded grid is a valid completed Sudoku.
- `demo.sh` exercises every feature end-to-end and must exit green.

## Definition of done
All 6 phases complete, all gates green, at least 1 stretch shipped (targeting
all 3), differential fuzzer clean over a large seed sweep, UNSAT proofs checked
independently.
