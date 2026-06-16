# Resolvent

**A from-scratch CDCL SAT solver in pure Python** — with a constraint-modeling
DSL, four real puzzle compilers, an *independent* UNSAT proof checker, and an
interactive, dependency-free HTML implication-graph visualizer.

Boolean satisfiability is the canonical NP-complete problem. A modern
**C**onflict-**D**riven **C**lause-**L**earning solver routinely defeats
instances with hundreds of thousands of variables by *learning from its own
mistakes*: every dead end it hits is analyzed, distilled into a new clause that
forbids the whole family of failures that led there, and used to leap back over
huge swaths of the search tree. Resolvent implements that full architecture —
no SAT library, no Graphviz, no JS frameworks — and then *proves it didn't
cheat*.

```
$ python3 -m resolvent.cli demo
$ python3 -m resolvent.cli sudoku examples/sudoku_hard.txt   # the "world's hardest"
$ python3 -m resolvent.cli queens 20
$ python3 -m resolvent.cli php 7 6 --check-proof             # pigeonhole, UNSAT + certificate
$ python3 -m resolvent.cli viz php -a 5 -b 4 --out report.html
```

## What it is

A single engine that turns many different problems into CNF, solves them, and
decodes the answer back — and when the answer is "no solution exists", hands you
a machine-checkable proof of that fact.

## How to run

No dependencies beyond Python 3.8+. From this folder:

```bash
python3 -m resolvent.cli <command> ...     # CLI
python3 -m unittest tests.test_resolvent   # 35-test suite (~1s)
./demo.sh                                   # full end-to-end tour
```

### Commands
| command | what it does |
|---|---|
| `solve FILE [--proof P] [--check-proof]` | solve a DIMACS CNF; optionally emit & verify a DRAT proof |
| `sudoku FILE` | solve any N²×N² Sudoku (compact, block, or spaced grid) |
| `queens N` | solve N-Queens |
| `color FILE -k K` | K-color a graph (edge-list file) |
| `php M N [--check-proof]` | pigeonhole PHP(M,N) + UNSAT certificate |
| `gen --vars V --ratio R -k K --seed S` | generate a random k-SAT instance |
| `verify FILE [--model M\|--proof P\|--count]` | check a model, check an UNSAT proof, or count models |
| `viz {php,queens,color,dimacs} --out F.html` | build the interactive HTML report |
| `demo` | quick built-in showcase |

Exit codes follow the SAT-competition convention: **10** = SATISFIABLE,
**20** = UNSATISFIABLE, **2** = error/indeterminate.

## Full feature list

**Core CDCL solver** (`solver.py`)
- Two-watched-literal unit propagation (BCP).
- VSIDS activity-based branching with a lazy binary heap + rescaling.
- 1-UIP conflict analysis with clause learning and **self-subsuming
  recursive minimization** of learned clauses.
- Non-chronological backjumping.
- Phase saving.
- Luby-sequence restarts.
- Clause-database reduction (`reduceDB`) with clause-locking and index remap.
- DIMACS read/write; full statistics.

**Constraint modeling layer** (`model.py`)
- Fresh (optionally named) boolean variables.
- Tseitin encoding of arbitrary boolean expressions: `AND/OR/NOT/XOR/IMPLIES/IFF`.
- Cardinality constraints: `at_least_one`, `at_most_one` (pairwise for small
  sets, Sinz sequential-counter for large), `exactly_one`, and
  `at_most_k / at_least_k / exactly_k`.

**Puzzle compilers** (`puzzles/`) — each encodes to CNF through the DSL and
decodes the model back to a human-readable answer:
- **Sudoku** (any perfect-square size), **N-Queens**, **graph K-coloring**,
  **pigeonhole**.

**Verification & certificates** (`proof.py`)
- Every SAT model is re-checked against the original clauses.
- Brute-force oracle and exact **#SAT model counter** (DPLL), cross-checked.
- **Independent DRAT-style UNSAT proof checker** by reverse unit propagation —
  re-derives the empty clause from the original formula + learned clauses
  *without trusting the solver*. Rejects tampered/invalid proofs.

**Interactive visualizer** (`viz.py`) — one self-contained HTML file, zero
dependencies:
- Hand-rolled layered layout of the **implication graph** for each captured
  conflict: decision literals, propagated literals, the conflict node κ, and the
  highlighted **1-UIP cut** that becomes the learned clause.
- Pan/zoom, per-node hover (level + reason clause), conflict stepper, the
  conflicting and learned clauses, backjump level, and live solver statistics.

**Extras**: random k-SAT generator at the hard phase-transition ratio.

## How it's built
```
DIMACS / DSL ─┐
puzzle input ─┼─► CNF (clause DB) ─► CDCL solver ─► SAT model  ─► decode / verify
              │                          │                     └─► HTML viz
              └─► Tseitin + cardinality  └─► UNSAT + DRAT proof ─► RUP checker
```
Pure Python 3 standard library only. The visualizer's JS is generated and
embedded; it uses no external libraries. (Node is used *only* in development to
syntax/runtime-check the generated JS — never at runtime.)

## Correctness / how it's verified
- **Differential testing:** thousands of random instances solved three ways
  (default, no-restart, no-reduce) and checked against a brute-force oracle;
  every SAT model re-validated; every UNSAT verdict independently proof-checked.
- **Known answers:** PHP(n+1,n) is UNSAT for all n; N-Queens 2 & 3 are UNSAT;
  the "world's hardest" Sudoku decodes to a valid grid; Petersen is 3- but not
  2-colorable; K₄ needs 4 colors.
- **Self-checks:** the model counter agrees with brute force on hundreds of
  instances; the proof checker accepts valid proofs and rejects fabricated ones.
- 35 unit tests, all green in ~1 second.

## Why I chose this today
The daily-build ledger already had a world generator, a regex engine, a
relational database, a Raft simulator, a physics engine, and an autodiff engine.
Missing was the *other* great pillar of practical computer science: **search and
constraint reasoning**. A CDCL solver is the most beautiful example — it's the
workhorse behind hardware verification, planning, and dependency resolution, and
its core (watched literals + 1-UIP learning + backjumping) is famously easy to
get *subtly* wrong in ways that still look like they work. That made it both
genuinely interesting to build and a perfect adversarial-review target. The
modeling layer and puzzle compilers show off SAT as a *universal* solver, and
the independent proof checker means you never have to take the solver's word for
"unsatisfiable."

## Where a human could take this next
- **Performance:** move from Python lists to arrays / a C extension; add
  literal-block-distance (LBD) clause scoring and Glucose-style aggressive
  reduction; chronological backtracking; inprocessing (vivification,
  subsumption).
- **Solver tech:** Luby + dynamic restart policies, target-phase rephasing,
  bounded variable elimination as preprocessing.
- **Reach:** a full DIMACS/DRAT toolchain compatible with external checkers
  (`drat-trim`); a MaxSAT / weighted layer; an assumptions interface for
  incremental solving; a Python `Model`-level API for arbitrary CSPs.
- **Visualizer:** animate propagation step-by-step, show the resolution
  derivation of each learned clause, and render the full search tree.

## Layout
```
resolvent/
  cnf.py        CNF + DIMACS I/O + model checking
  solver.py     the CDCL engine
  model.py      Tseitin + cardinality modeling DSL
  proof.py      brute oracle, #SAT counter, RUP/DRAT proof checker
  puzzles/      sudoku, nqueens, coloring, pigeonhole
  viz.py        interactive HTML report generator
  cli.py        command-line interface
tests/          35-test unittest suite
examples/       sample Sudoku grid + Petersen graph
demo.sh         end-to-end tour
PLAN.md  REVIEW.md
```
