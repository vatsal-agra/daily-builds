# Conflux — Plan

## Concept
**Conflux** is a from-scratch **CDCL SAT solver** — the modern algorithm that
powers industrial-strength Boolean satisfiability solving — built in pure Python
with no dependencies, plus a single-file interactive HTML visualizer that
animates the *conflict-driven clause learning* loop a step at a time.

A SAT solver answers one deceptively simple question: given a Boolean formula in
conjunctive normal form (an AND of ORs of literals), is there an assignment of
true/false to the variables that makes the whole thing true? The naive answer is
to try all `2^n` assignments. CDCL is the family of techniques that lets real
solvers chew through formulas with *millions* of variables: it watches literals
lazily, propagates forced consequences, and — the crucial trick — when it hits a
dead end it doesn't just backtrack, it *analyzes why* the conflict happened,
derives a brand-new clause that forbids that whole class of mistakes, and jumps
back over everything irrelevant.

## Why it's interesting
- SAT is the canonical NP-complete problem; *every* problem in NP reduces to it.
  A good SAT solver is a general-purpose problem-solving engine — you encode your
  problem as clauses and the solver does the search.
- CDCL is one of the great practical algorithms: the implication graph, 1-UIP
  conflict analysis, non-chronological backjumping, VSIDS activity heuristics,
  two-watched-literal propagation, and restarts all interlock beautifully.
- It is *brutally verifiable*: a claimed SAT model can be checked in linear time,
  and a claimed UNSAT result can be backed by a **DRAT proof** that an independent
  checker validates clause-by-clause. No "trust me" — every answer carries a
  certificate.
- It produces something you can *watch*: the assignment trail growing and
  collapsing, the implication graph fanning out to a conflict, learned clauses
  accumulating. That makes for a genuinely illuminating visualizer.

## Architecture
```
conflux/
  cnf.py        CNF / clause / literal model + DIMACS read & write
  solver.py     the CDCL engine (the heart):
                  - two-watched-literal unit propagation
                  - VSIDS branching with activity decay
                  - 1-UIP conflict analysis -> learned clause
                  - non-chronological backjumping
                  - Luby-sequence restarts + phase saving
                  - recursive learned-clause minimization
                  - optional DRAT proof recording
  proof.py      independent DRAT/RUP proof checker for UNSAT certificates
  encoders.py   problem -> CNF encoders, each with a decoder + validator:
                  - Sudoku (9x9 and NxN)
                  - N-Queens
                  - Graph k-coloring
                  - Pigeonhole PHP(n+1, n)  (classic UNSAT, exercises learning)
  rand3sat.py   uniform random k-SAT generator + phase-transition sweep
  trace.py      structured step trace (for the visualizer / explain mode)
  viz.py        generates a single-file HTML visualizer (embeds a JS solver)
  cli.py        argparse front-end; __main__.py wires `python -m conflux`
web/
  solver.js     JS mirror of the CDCL core (embedded into the HTML by viz.py;
                also run under Node for Python<->JS parity tests)
tests/
  run_tests.py  unittest suite (see Phase 5)
demo.sh         one-shot end-to-end demonstration of every feature
```

## Feature list

### Required (must fully work end-to-end)
1. **CDCL engine** — two-watched-literal unit propagation, VSIDS decision
   heuristic, 1-UIP conflict analysis with learned clauses, non-chronological
   backjumping, Luby restarts, and phase saving. Decides SAT/UNSAT.
2. **DIMACS I/O + certified answers** — read/write standard DIMACS CNF; every
   SAT result returns a model that an independent checker confirms satisfies the
   formula; every UNSAT result is backed by a DRAT proof validated by an
   independent proof checker.
3. **Problem encoders** — Sudoku, N-Queens, graph coloring, and pigeonhole, each
   reduced to CNF, solved, and decoded back to a solution that a *separate*
   validator confirms is legal (not just "the solver said so").
4. **Interactive HTML visualizer** — a self-contained single-file page (JS mirror
   of the engine) that steps through the CDCL loop: live assignment trail by
   decision level, the implication graph for the current conflict, the growing
   list of learned clauses, VSIDS activity, with play/step/scrub controls and a
   Sudoku-solving view.

### Stretch
5. **Random k-SAT phase transition** — generate uniform random 3-SAT and sweep
   the clause/variable ratio to empirically reveal the famous satisfiability
   threshold near α ≈ 4.26 (probability-of-SAT and median solve-cost curves).
6. **DRAT proof checker** — a fully independent reverse-unit-propagation proof
   verifier that validates UNSAT certificates clause-by-clause (also catches a
   *wrong* proof).
7. **`explain` / anatomy mode** — ASCII rendering of the implication graph and
   the 1-UIP cut for a chosen conflict, so the learned clause is human-readable.

## Correctness gates (how I'll know it's real, not "basically working")
- **Brute-force oracle:** for small instances (n ≤ ~16) enumerate all `2^n`
  assignments and confirm Conflux's SAT/UNSAT verdict matches exactly.
- **Model verification:** every SAT model is independently checked against the CNF.
- **Proof verification:** every UNSAT proof passes the independent DRAT checker;
  a deliberately corrupted proof is rejected.
- **Decode-and-validate:** Sudoku/Queens/coloring solutions pass a hand-written
  rules validator, and known puzzles produce the known unique solution.
- **Pigeonhole:** PHP(n+1,n) is reported UNSAT with a valid proof.
- **JS≡Python parity:** the JS mirror returns the same SAT/UNSAT verdict (and
  satisfying models) as the Python engine on a shared instance set, run under Node.
- **Phase transition:** the empirical SAT probability crosses 0.5 near α ≈ 4.26.

## Non-goals
- Beating MiniSat on speed. The goal is a *correct, complete, legible* modern
  solver with certificates and a visualizer — clarity over raw throughput.
