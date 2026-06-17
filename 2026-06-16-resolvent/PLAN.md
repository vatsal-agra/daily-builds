# Resolvent — Plan

## Concept
**Resolvent** is a modern **CDCL SAT solver** written from scratch in pure Python —
the kind of engine that sits underneath model checkers, dependency resolvers,
hardware verification, and AI planners. You give it a Boolean formula in
Conjunctive Normal Form (CNF); it decides whether *any* assignment of true/false
to the variables makes the whole formula true (SAT), and if so hands you one — or
*proves* that none can exist (UNSAT).

A naive solver tries all `2^n` assignments. Resolvent is the real thing:
**Conflict-Driven Clause Learning** (CDCL), the algorithm that powers MiniSAT,
Glucose, CaDiCaL and friends. When the search hits a dead end (a *conflict*), it
doesn't just backtrack one step — it *analyzes why* the conflict happened,
derives a brand-new clause that forbids that whole class of mistakes
(the **1-UIP learned clause**), and jumps back many levels at once
(**non-chronological backtracking**). Learned clauses + smart branching turn an
exponential brute-force into something that routinely cracks formulas with
thousands of variables.

## Why it's interesting
- SAT is the **canonical NP-complete problem** — Cook–Levin's original. A real CDCL
  solver is a small, beautiful machine where five classic ideas
  (unit propagation, clause learning, watched literals, activity heuristics,
  restarts) compose into something genuinely powerful.
- It is **falsifiable and self-checking**: a SAT answer can be verified by plugging
  the model back into the clauses; an UNSAT answer can be backed by a **machine-
  checkable resolution/DRUP proof**. So I can prove the solver is honest, not just
  "looks right."
- It's a **universal reduction target**: graph coloring, N-Queens, Sudoku,
  scheduling, and pigeonhole all compile *down* to CNF. So one engine solves a
  whole zoo of puzzles — and decoding the model back into a colored graph or a
  filled Sudoku grid makes a great, visual demo.
- The **implication graph** — the data structure CDCL analyzes at each conflict —
  is gorgeous to visualize: decisions, forced propagations, and the cut that
  produces the learned clause.

## Architecture
```
DIMACS text ──parse──► CNF (clauses, vars)
                          │
                  ┌───────┴────────┐
                  ▼                ▼
            brute-force        CDCL solver
            (oracle, ≤20 vars)   │
                                 ├─ trail + decision levels
                                 ├─ two-watched-literal unit propagation
                                 ├─ 1-UIP conflict analysis ──► learned clause
                                 ├─ non-chronological backjump
                                 ├─ VSIDS variable activity + phase saving
                                 ├─ Luby restarts
                                 └─ clause-DB reduction (LBD/activity)
                                 │
                        ┌────────┼─────────┐
                        ▼        ▼          ▼
                    SAT model  UNSAT     DRUP proof log
                        │      + proof        │
                   verify ✓               proof checker ✓

encoders:  n-queens / sudoku / graph-color / pigeonhole  ──► CNF
decoder:   model ──► colored graph / filled grid (pretty printed)
viz:       implication graph + learned-clause cut ──► single-file HTML/SVG
```

Everything is pure Python 3 stdlib. No third-party deps. Determinism is controlled
by a seed so any run replays exactly.

## Feature list

### Required (core)
1. **DIMACS CNF front-end** — a tolerant parser for the standard `p cnf V C`
   format (comments, blank lines, clauses split across lines, `%`/trailing `0`
   handling) with **positioned, human-readable errors**, plus a serializer back to
   DIMACS. A small CNF builder API for programmatic construction.
2. **CDCL solver core** — trail with decision levels, **two-watched-literal** unit
   propagation, **1-UIP conflict analysis** producing a learned clause, and
   **non-chronological backjumping**. Returns SAT+model or UNSAT. No brute force in
   the hot path.
3. **Heuristics & search control** — **VSIDS** activity-based branching with decay,
   **phase saving**, **Luby-sequence restarts**, and **learned-clause database
   reduction**. Tunable, and each demonstrably changes behavior/stats.
4. **Correctness harness** — a **brute-force oracle** (truth-table) for small
   formulas and a **differential fuzzer** that generates random CNF and asserts
   Resolvent's SAT/UNSAT verdict matches the oracle on thousands of instances;
   plus a model verifier that re-checks every satisfying assignment.

### Stretch
5. **Problem encoders + decoder** — compile **N-Queens**, **graph coloring**,
   **Sudoku**, and **pigeonhole** into CNF, solve, and **decode the model back**
   into a human-readable board/coloring. (Pigeonhole gives guaranteed-UNSAT
   stress tests.)
6. **Interactive implication-graph visualizer** — a self-contained HTML page (no
   deps, no CDN) that renders the implication graph at a chosen conflict: decision
   nodes, propagation edges labeled by the clause that forced them, the conflict
   node, and the **1-UIP cut** that yields the learned clause. Custom layered
   layout — no Graphviz.
7. **DRUP UNSAT-proof logging + checker** — emit a DRUP-style proof (sequence of
   learned clauses) for UNSAT runs, and ship an **independent proof checker** that
   replays the proof by reverse-unit-propagation to confirm the empty clause is
   derivable. An UNSAT answer you can *trust*.

## CLI surface
- `solve <file.cnf>` — solve, print SAT model or UNSAT (+ stats), optional `--proof`
- `gen` — generate random k-SAT at a chosen clause/var ratio (seeded)
- `check <file.cnf> <model>` — verify a model satisfies a formula
- `fuzz` — differential test vs brute-force oracle over many random instances
- `bench` — phase-transition sweep (SAT probability vs clause/var ratio)
- `encode <queens|sudoku|color|pigeonhole>` — emit CNF for a named problem
- `solve-puzzle <queens N | sudoku FILE | color FILE K>` — encode→solve→decode
- `viz <file.cnf>` — solve and emit the implication-graph HTML
- `proofcheck <file.cnf> <proof.drup>` — independently verify an UNSAT proof

## Verification plan
- Brute-force differential fuzz: thousands of seeded random CNFs, zero verdict
  mismatches.
- Every SAT model re-verified clause-by-clause.
- Every UNSAT result on small instances cross-checked against the oracle AND
  (where produced) its DRUP proof replayed by the independent checker.
- Known-answer puzzles: N-Queens solution count sanity (N=8 solvable), pigeonhole
  PHP(n+1,n) is UNSAT, a real Sudoku decodes to a valid completed grid.
- Stats sanity: restarts fire, clauses are learned and deleted, VSIDS scores move.
```
```
