# Crux

**A modern CDCL SAT solver, written from scratch in pure Python — plus the
tooling that makes a solver actually useful.**

Crux decides Boolean satisfiability with the real algorithm behind every
competitive solver since Chaff/MiniSat — **Conflict-Driven Clause Learning** — and
wraps it in problem encoders, an independent correctness oracle, UNSAT proof
certificates, exact model counting, and an interactive visualizer of the one idea
at the heart of CDCL: *learning a new clause from every contradiction.*

No third-party dependencies. Python 3.8+. (Node is used only for an optional
headless test of the generated HTML.)

```bash
./demo.sh                                   # tour every feature + run the tests
python3 -m crux decode sudoku examples/sudoku_hard.txt
python3 -m crux fuzz --trials 2000          # prove the engine correct vs brute force
```

---

## What it is

A `CNF` formula goes in (from a DIMACS file or a built-in encoder); a verified
**SAT model** or an **UNSAT** verdict (optionally with a checkable proof) comes out.

The solver is genuine CDCL, not toy DPLL:

- **Two-watched-literals** unit propagation — the data structure that makes BCP fast.
- **1-UIP conflict analysis** producing an *asserting* learned clause.
- **Non-chronological backjumping** to the second-highest level in that clause.
- **VSIDS** activity-based branching with exponential decay.
- **Phase saving** for decisions.
- **Luby-sequence restarts** and **activity-based learned-clause deletion**.
- **Clause minimization** (sound self-subsuming resolution).
- Optional **assumptions** (incremental-style solving) and a **conflict budget**.

## How to run

Everything is driven through `python3 -m crux <subcommand>`:

| Command | What it does |
|---|---|
| `solve [file]` | Solve a DIMACS CNF (stdin if no file). `--max-conflicts N` to bound. |
| `check <file> [model]` | Verify a model satisfies a formula. |
| `gen` | Generate a random DIMACS instance (`--vars --clauses --width --seed`). |
| `encode <problem> [input]` | Encode sudoku / queens / coloring / pigeonhole to DIMACS. |
| `decode <problem> [input]` | Solve an encoded problem and print the human solution. |
| `fuzz` | Differential-test the engine against the brute-force oracle. |
| `count [file]` | Exact #SAT model count (`--verify` cross-checks brute force). |
| `proof [file]` | Solve, and if UNSAT, emit + independently check a DRUP/RUP proof. |
| `viz` | Generate the interactive HTML conflict-analysis visualizer. |
| `demo` | Guided tour of every feature. |

**Output** follows the SAT-competition convention: `s SATISFIABLE` /
`s UNSATISFIABLE` / `s UNKNOWN`, a `v <literals> 0` model line, and exit codes
**10** (SAT) / **20** (UNSAT) / **0** (UNKNOWN). `c ...` lines carry comments/stats.

```bash
# random 3-SAT, then verify the model it found
python3 -m crux gen --vars 50 --clauses 213 --seed 1 | python3 -m crux solve

# a real 9x9 Sudoku, decoded back to a grid
python3 -m crux decode sudoku examples/sudoku_hard.txt

# pigeonhole is UNSAT when pigeons > holes — prove it, then check the proof
python3 -m crux encode pigeonhole -m 6 -n 5 | python3 -m crux proof

# build the visualizer and open it
python3 -m crux viz --problem pigeonhole -m 5 -n 4 --out web/crux-viz.html
```

## Full feature list

**Core (required)**
1. **CDCL engine** — watched literals, 1-UIP learning, backjumping, VSIDS, phase
   saving, Luby restarts, clause deletion, minimization; full search statistics.
2. **DIMACS I/O + verified models** — tolerant parser (comments, multi-line
   clauses, missing trailing `0`, `%` trailer) with error context; `check` validates
   any model.
3. **Differential oracle** — an independent exhaustive solver + a fuzzer; thousands
   of random formulas agree on SAT/UNSAT and every model is re-verified.
4. **Encoders + decoders** — Sudoku (any n²×n²), graph k-colouring, N-Queens, and
   pigeonhole, using a Sinz sequential (O(n)) at-most-one encoding.

**Stretch (all shipped)**
5. **Interactive conflict visualizer** — a self-contained HTML page that embeds the
   solver's *real* recorded conflicts and draws each implication graph: decisions,
   propagations, the ⊥ conflict node, the highlighted **1-UIP**, and the learned
   clause — steppable with ◀/▶ or the slider.
6. **DRUP/RUP UNSAT proofs** — the solver logs its learned clauses as a resolution
   proof; an independent checker (sharing no solver code) certifies UNSAT by reverse
   unit propagation.
7. **Exact model counting (#SAT)** — a DPLL counter, cross-checked against brute force.

## Why I chose this today

The previous daily builds were from-scratch *systems* (a database, a Raft
simulator, a physics engine, an autodiff engine). SAT felt like the right kind of
different: it's the canonical NP-complete problem, and a CDCL solver is a small
amount of code that does something genuinely deep — it *learns from its own
mistakes*, and the clauses it derives are resolution proofs. The watched-literals
scheme and 1-UIP analysis are famously fiddly and easy to get subtly wrong, which
makes them a perfect target for differential fuzzing (the adversarial review
confirmed the engine but caught a 1883× memory blow-up and a dead, misleading
parameter). And because SAT is a universal substrate, one correct engine instantly
solves Sudoku, colouring, queens, and pigeonhole through encoding alone — a very
satisfying payoff to visualize.

## How it's verified

- **2500-formula differential fuzz** vs an exhaustive oracle, across varied restart
  schedules: zero disagreements; every SAT model independently re-checked.
- **All four encoders** validated structurally (a solved Sudoku really is a valid
  Sudoku; queens really don't attack; odd cycles really need 3 colours).
- **Model counting** matches brute force over hundreds of random formulas.
- **UNSAT proofs** for pigeonhole and random instances pass an independent checker;
  a bogus certificate for a satisfiable formula is rejected.
- **The visualizer** is headless-tested: every conflict snapshot renders without a
  JS error.
- 27 unit tests + `demo.sh`, all green.

## Where a human could take this next

- **Speed**: the hot loops are pure Python. A watched-literal rewrite in C/Rust (or
  bitset trails) would make industrial benchmarks tractable; right now Crux is built
  for clarity and correctness, not SATComp throughput.
- **Better proofs**: emit standard **DRAT** (with RAT steps, not just RUP) and pipe
  to `drat-trim`; add proof *trimming* and an LRAT backend.
- **Stronger heuristics**: LBD-based clause deletion, EVSIDS, Glucose-style restart
  blocking, chronological backtracking, in-processing (vivification, bounded
  variable elimination).
- **More front-ends**: a cardinality/PB layer, an `at-most-k` encoder, a Tseitin
  transformer so arbitrary Boolean circuits compile straight to CNF.
- **MaxSAT / optimization**: layer a core-guided or linear-search MaxSAT loop on top
  of the incremental assumption interface that's already here.

## Project layout

```
crux/
  cnf.py        CNF + DIMACS parse/write + model checking
  solver.py     the CDCL engine (trail, watches, BCP, VSIDS, analyze, restarts)
  brute.py      exhaustive reference solver + model counter (the oracle)
  encoders.py   sudoku / coloring / queens / pigeonhole  <->  CNF
  counter.py    exact #SAT model counting
  proof.py      independent DRUP/RUP UNSAT-certificate checker
  viz.py        generates the self-contained HTML visualizer
  demo.py       the guided feature tour
  cli.py        argument parsing + subcommands
tests/          27-test unittest suite
examples/       sample Sudoku + graph inputs
web/            generated visualizer output
PLAN.md REVIEW.md   the build's plan and adversarial review
```
