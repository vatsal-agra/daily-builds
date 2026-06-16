# Backjump — a CDCL SAT solver from scratch

## Concept
A modern **conflict-driven clause-learning (CDCL) Boolean satisfiability solver**,
built from nothing but the Python standard library, plus the machinery that makes
a SAT solver trustworthy and useful:

- a real CDCL engine (the same algorithmic family as MiniSat / Glucose),
- a **verified UNSAT proof** (every learned clause checked by reverse-unit-propagation,
  and a full resolution refutation reaching the empty clause for unsatisfiable
  instances),
- **encoders** that turn real combinatorial puzzles (Sudoku, N-Queens, graph
  colouring, pigeonhole) into CNF, solve them, and decode the answer back, and
- an **interactive single-file HTML visualizer** that replays a real solve:
  the decision trail, unit propagations, the implication graph, the 1-UIP
  conflict cut, learned clauses, VSIDS activity and restarts.

## Why it's interesting
SAT is the canonical NP-complete problem, and CDCL is one of the great practical
algorithms of computer science — it routinely cracks instances with millions of
variables that brute force could never touch. The magic is subtle and rarely seen:
non-chronological *backjumping*, learning a clause from the *first unique implication
point* of an implication graph, two-watched-literal propagation that touches almost
nothing, and an activity heuristic (VSIDS) that lets the search "focus" on the hard
core of a problem. Implementing it correctly — and then *proving* the UNSAT answers
and *seeing* the implication graph evolve — turns a black box into something you can
actually understand.

It also doesn't overlap with any prior daily build: it's not a database, not a
consensus protocol, not a regex/automata engine, not autodiff, not physics, not
procedural generation. It's combinatorial search.

## Architecture
```
DIMACS .cnf ──► parser ──► CNF (clauses over int literals)
                              │
                              ▼
                    ┌──────────────────┐
                    │   CDCL solver    │   trail, decision levels
                    │  - 2-watched lit │   unit propagation
                    │  - 1-UIP analyze │   conflict → learned clause
                    │  - backjump      │   non-chronological
                    │  - VSIDS + decay │   branching heuristic
                    │  - Luby restarts │
                    │  - clause DB      │   (learned clause store)
                    └──────────────────┘
                       │            │
              SAT + model      UNSAT + resolution proof
                       │            │
        ┌──────────────┴───┐    ┌───┴───────────────┐
        │  model verifier  │    │  proof checker     │ (RUP / empty clause)
        └──────────────────┘    └────────────────────┘
                       │
   encoders (sudoku / nqueens / coloring / pigeonhole)  ◄─► decode
                       │
        trace recorder ──► embedded JSON ──► single-file HTML visualizer
```

Everything is deterministic given the input (fixed tie-breaking, seeded where any
randomness is used), so a solve replays identically and any bug is reproducible.

## Feature list

### Required (must fully work end-to-end)
1. **CDCL core.** DIMACS parser + a complete conflict-driven solver:
   two-watched-literal unit propagation, 1-UIP conflict analysis with clause
   learning, non-chronological backjumping, VSIDS branching with activity decay,
   and Luby-sequence restarts. Returns SAT (with a model) or UNSAT.
2. **Verified answers.** For SAT, independently check the returned model satisfies
   every original clause. For UNSAT, emit a resolution/RUP proof and **check it**:
   each learned clause must follow from the formula by reverse unit propagation,
   and the refutation must derive the empty clause. A wrong "UNSAT" cannot pass.
3. **Problem encoders + decoders.** Turn Sudoku, N-Queens, and graph k-colouring
   into CNF, solve them, and decode the model back into a human-readable solution
   (a filled grid, queen placements, a colour assignment). Real CNF, real solve,
   real decode — no special-case solvers.
4. **Interactive HTML visualizer.** A generated, dependency-free single file that
   replays an actual recorded solve: step/play through decisions and propagations,
   see the implication graph and the 1-UIP cut at each conflict, the growing trail
   with decision levels, learned clauses, VSIDS bars, and restart markers.

### Stretch
5. **CLI + statistics + DIMACS I/O.** `solve / sudoku / queens / color / pigeon /
   gen / fuzz / viz` subcommands; full solver stats (decisions, conflicts,
   propagations, learned clauses, restarts, max depth); read/write DIMACS; print
   models and proofs.
6. **Differential fuzzer.** Generate random CNF, solve with Backjump, and
   cross-check every answer against an independent brute-force truth oracle
   (and, for UNSAT, against the proof checker). A 3-SAT phase-transition demo
   showing the satisfiability cliff near clause/variable ratio ≈ 4.26.
7. **Model counting (#SAT) / AllSAT** via blocking clauses — enumerate or count
   all satisfying assignments for small instances, cross-checked against brute force.

## Stack
Pure Python 3 standard library (no third-party deps) for the solver, encoders,
proof checker, CLI and tests. The visualizer is generated self-contained
HTML/CSS/JS (the solve trace is computed in Python and embedded as JSON, so the
browser just *replays* the real solver's decisions — it never re-implements them).

## Definition of done
All 4 required + ≥1 stretch features working; adversarial review in REVIEW.md with
every issue fixed; a test/demo script exercising every feature, green; README +
LEDGER entry.
