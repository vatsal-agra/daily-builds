# Resolvent

A **CDCL SAT solver built from scratch in pure Python** — no dependencies, no
`pip install`, just the standard library. SAT (Boolean satisfiability) is the
canonical NP-complete problem and the workhorse behind hardware verification,
software model checking, AI planning, and automated theorem proving. Resolvent
implements the modern conflict-driven clause-learning architecture that makes
real-world SAT solvers shockingly effective, and wraps it in a CLI that can
solve Sudoku, color graphs, place queens, and *prove* the pigeonhole principle —
with every UNSAT answer independently re-checked by a separate verifier.

```
$ python3 -m resolvent decode sudoku
 5 3 4 | 6 7 8 | 9 1 2
 6 7 2 | 1 9 5 | 3 4 8
 1 9 8 | 3 4 2 | 5 6 7
-------+-------+-------
 8 5 9 | 7 6 1 | 4 2 3
 4 2 6 | 8 5 3 | 7 9 1
 7 1 3 | 9 2 4 | 8 5 6
-------+-------+-------
 9 6 1 | 5 3 7 | 2 8 4
 2 8 7 | 4 1 9 | 6 3 5
 3 4 5 | 2 8 6 | 1 7 9
c valid completed Sudoku: True
```

## What it is

Resolvent decides whether a Boolean formula in CNF (a conjunction of clauses,
each a disjunction of literals) can be made true. It implements, from first
principles:

- **Two-watched-literal unit propagation** — the lazy data structure that makes
  propagation fast by watching only two literals per clause.
- **1-UIP conflict analysis + clause learning** — when the search hits a
  contradiction, it resolves the implication graph back to the first unique
  implication point, learns a new clause that prevents the same dead end, and
  **backjumps non-chronologically**.
- **VSIDS branching** with exponential activity decay, **phase saving**, **Luby
  restarts**, and **activity-based clause-database reduction**.
- **Self-subsuming clause minimization** of learned clauses.

It is correct by construction *and* by relentless testing: every result is
cross-checked against independent oracles, every model is verified against the
original formula, and every UNSAT proof is re-checked by code that shares no
search logic with the solver.

## How to run

No installation needed (Python 3.8+). From this directory:

```bash
python3 -m resolvent demo            # guided tour of every feature (self-checking)
./demo.sh                            # tests + tour + fuzz; exits non-zero on any failure
python3 -m unittest tests.test_resolvent -v   # the 27-test suite
```

CLI subcommands:

```bash
# Solve a DIMACS CNF file; prints SAT/UNSAT, a verified model, and statistics.
python3 -m resolvent solve examples/sat_simple.cnf

# Prove UNSAT and independently RUP-check the emitted proof.
python3 -m resolvent verify examples/unsat_simple.cnf

# Compile a problem to DIMACS CNF (stdout) ...
python3 -m resolvent encode queens 8 > queens8.cnf
# ... or solve it and pretty-print the answer:
python3 -m resolvent decode sudoku                  # built-in puzzle
python3 -m resolvent decode sudoku "<81-char grid>" # your own
python3 -m resolvent decode queens 12
python3 -m resolvent decode coloring petersen 3     # graphs: petersen, k4, c5, wheel6
python3 -m resolvent decode php 6                    # pigeonhole, UNSAT

# Render the first conflict's implication graph to standalone HTML/SVG.
python3 -m resolvent viz examples/unsat_simple.cnf conflict.html

# Differential-test the solver against an exhaustive oracle.
python3 -m resolvent fuzz --n 2000 --seed 0 --maxvars 10
```

Exit codes follow the SAT-competition convention: **10** = SATISFIABLE,
**20** = UNSATISFIABLE, **2** = input error.

## Full feature list

**Core (required)**
1. **DIMACS CNF front-end** — strict, line-numbered parser (comments, `p cnf`
   header, multi-line clauses, tautology/duplicate handling) and a writer that
   round-trips.
2. **CDCL solver** — two-watched-literal propagation, 1-UIP conflict analysis,
   clause learning, non-chronological backjumping, self-subsuming minimization.
3. **Search heuristics** — VSIDS with decay, phase saving, Luby restarts,
   learned-clause DB reduction.
4. **`solve` CLI + self-verification** — SAT/UNSAT, a model checked against the
   original clauses before it's trusted, and full search statistics.

**Stretch (all three shipped)**
5. **Problem encoders** — Sudoku (9×9), graph k-coloring, N-Queens, and
   pigeonhole compiled to CNF, with solutions decoded and validated back in the
   problem's own terms.
6. **Independent proof checking + differential fuzzer** — the solver emits a
   DRAT-style clausal proof on UNSAT; a separate **RUP checker** (no shared
   search code) verifies the empty clause is derivable. A fuzzer cross-checks
   verdicts against an exhaustive truth-table oracle and a recursive-DPLL oracle.
7. **Implication-graph visualizer** — a standalone, dependency-free HTML/SVG
   view of the first conflict: decision vs. implied literals laid out by decision
   level, reason edges, the conflict node κ, and the highlighted 1-UIP cut with
   the learned clause.

## Why I chose this today

The previous daily builds include a regex engine, a relational database, a Raft
simulator, a physics engine, and an autodiff engine — all "implement a famously
tricky system from scratch and prove it correct." A CDCL SAT solver is the
natural next member of that family: it's a tiny amount of code wrapped around
several genuinely deep ideas (watched literals, 1-UIP learning, VSIDS), it's a
*general reasoning engine* so one solver cracks Sudoku, coloring, and queens
alike, and it's exactly the kind of thing where a subtle bug hides until heavy
search triggers it — which is what makes the adversarial-review and
differential-testing gates earn their keep. (And they did: review found a VSIDS
heap bug that produced *false SAT* answers on bigger instances; see REVIEW.md.)

## Where a human could take this next

- **Performance:** the propagation loop and VSIDS heap are written for clarity in
  pure Python. A blocking-literal optimization, watch-list cache locality, and a
  proper indexed binary heap (or porting the hot loop to C/Rust) would move it
  from "solves Sudoku instantly" to "solves competition benchmarks."
- **Preprocessing/inprocessing:** bounded variable elimination, subsumption, and
  vivification would shrink real formulas dramatically.
- **Stronger restarts & deletion:** Glucose-style LBD (literal block distance)
  clause scoring and adaptive restarts typically beat the Luby + activity scheme
  used here.
- **Full DRAT proofs:** emit deletion steps and clause-IDs in the standard DRAT
  text format so proofs can be checked by `drat-trim`, and add UNSAT-core
  extraction.
- **Incremental solving / assumptions:** a `solve_under_assumptions` API would
  enable MaxSAT, optimization, and a much richer encoder library (scheduling,
  routing, circuit equivalence).
- **A real front-end:** an in-browser version (the engine ports cleanly to JS,
  as earlier builds did) that animates propagation and conflict analysis live.

## Project layout

```
resolvent/
  cnf.py         CNF model + DIMACS reader/writer
  solver.py      the CDCL engine
  encoders.py    Sudoku / coloring / queens / pigeonhole <-> CNF
  proof.py       independent RUP UNSAT-proof checker
  bruteforce.py  truth-table + DPLL oracles for differential testing
  viz.py         implication-graph HTML/SVG renderer
  cli.py         command-line interface
  demo.py        self-checking feature tour
tests/           unittest suite (parser, solver, differential, encoders, proof, viz, CLI)
examples/        sample CNFs + a generated conflict graph
PLAN.md REVIEW.md demo.sh
```
