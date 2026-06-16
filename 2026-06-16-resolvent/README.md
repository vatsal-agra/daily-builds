# Resolvent

A **CDCL SAT solver** written from scratch in pure Python 3 (no dependencies) —
the algorithm that powers modern model checkers, dependency resolvers, hardware
verification, and AI planners. Give it a Boolean formula in CNF; it decides
**SAT** (and hands you a satisfying assignment) or **UNSAT** (and can hand you a
machine-checkable proof that *no* assignment exists).

It is the real machine, not a toy DPLL: **conflict-driven clause learning** with
1-UIP analysis, **two-watched-literal** unit propagation, **VSIDS** branching,
**phase saving**, **Luby restarts**, and **learned-clause database reduction** —
plus a brute-force oracle it's differentially tested against, a zoo of problem
encoders, a DRUP proof checker, and an interactive implication-graph visualizer.

```
$ python3 -m resolvent solve-puzzle queens --n 8
s SATISFIABLE
. . . . . . . Q
. Q . . . . . .
. . . . Q . . .
. . Q . . . . .
Q . . . . . . .
. . . . . . Q .
. . . Q . . . .
. . . . . Q . .
```

## What it is

SAT — is there an assignment of true/false to variables that makes every clause
true? — is the canonical NP-complete problem (Cook–Levin). A naive solver tries
all `2^n` assignments. Resolvent instead *learns from its mistakes*: when search
hits a conflict, it analyzes the **implication graph**, derives a new clause that
forbids that entire class of dead-ends (the **1-UIP learned clause**), and jumps
back many levels at once. Learning + smart branching turn exponential search into
something that cracks structured instances with thousands of variables in
milliseconds.

## How to run

No install, no dependencies — just Python 3.8+.

```bash
cd 2026-06-16-resolvent

# Run everything end-to-end (tests + every CLI feature):
./demo.sh

# Or the in-process tour:
python3 -m resolvent demo

# Test suite (includes a 1500-case brute-force differential gate):
python3 -m unittest discover -s tests -v
```

### CLI

| Command | What it does |
|---|---|
| `solve <f.cnf> [--proof p.drup]` | Solve a DIMACS CNF; print model or UNSAT (+ DRUP proof) |
| `gen --vars V --clauses C [--k K]` | Generate a seeded random k-SAT instance |
| `check <f.cnf> <model>` | Verify a model satisfies a formula |
| `fuzz -n N` | Differential test vs the brute-force oracle |
| `bench` | Phase-transition sweep: P(SAT) vs clause/var ratio |
| `encode <queens\|sudoku\|color\|pigeonhole>` | Emit CNF for a named problem |
| `solve-puzzle <problem>` | encode → solve → **decode** back to a board/coloring |
| `viz <f.cnf> --out g.html` | Solve and emit the implication-graph HTML |
| `proofcheck <f.cnf> <p.drup>` | **Independently** verify an UNSAT proof |

Exit codes follow the SAT-competition convention: `10` = SAT, `20` = UNSAT.

```bash
python3 -m resolvent gen --vars 60 --clauses 256 --seed 1 --out r.cnf
python3 -m resolvent solve r.cnf
python3 -m resolvent solve-puzzle sudoku                 # default hard grid
python3 -m resolvent solve-puzzle pigeonhole --holes 5 --proof php.drup
python3 -m resolvent encode pigeonhole --holes 5 --out php.cnf
python3 -m resolvent proofcheck php.cnf php.drup         # VERIFIED — UNSAT
python3 -m resolvent viz r.cnf --out impl.html           # open in any browser
```

## Features

**Required (core)**
1. **DIMACS front-end** — tolerant parser (comments, blank lines, split clauses,
   SATLIB `%` marker) with positioned, human-readable errors; serializer; a
   programmatic CNF builder.
2. **CDCL core** — trail with decision levels, two-watched-literal propagation,
   1-UIP conflict analysis producing learned clauses, non-chronological
   backjumping. No brute force in the hot path.
3. **Heuristics & search control** — VSIDS activity branching with decay, phase
   saving, Luby restarts, and learned-clause DB reduction (LBD/activity based).
   Each demonstrably changes the search (VSIDS off ≈ 7× more conflicts).
4. **Correctness harness** — a brute-force truth-table oracle and a differential
   fuzzer asserting Resolvent's verdict matches it across thousands of random
   instances; every SAT model re-verified clause-by-clause.

**Stretch**
5. **Problem encoders + decoder** — N-Queens, graph coloring, Sudoku, and the
   pigeonhole principle compiled to CNF, solved, and decoded back into a
   human-readable board/coloring. (Pigeonhole = guaranteed-UNSAT stress tests.)
6. **Implication-graph visualizer** — a self-contained, dependency-free HTML
   page (custom layered layout, no Graphviz/CDN) rendering the conflict's
   implication graph: decision vs propagated nodes, edges labeled by the forcing
   clause, the conflict node, and the orange 1-UIP cut that yields the learned
   clause. Pan / zoom / hover-to-trace.
7. **DRUP UNSAT-proof logging + independent checker** — emit a DRUP proof for
   UNSAT runs and verify it with a *separate* reverse-unit-propagation checker.
   An UNSAT answer you can trust, not just take on faith.

## Verification (Phase 5)

- **29 tests**, including a **1500-instance** brute-force differential gate
  spanning the SAT/UNSAT phase transition — **zero** verdict mismatches, **zero**
  invalid models.
- All five heuristic on/off configurations are independently checked for
  soundness against the oracle.
- 25+ independently-found random UNSAT instances: every DRUP proof verified.
- Known answers: N-Queens N≥4 solvable / N∈{2,3} unsolvable; K₄ needs 4 colors;
  pigeonhole PHP(n+1,n) is UNSAT; a hard Sudoku decodes to a valid completed grid.
- The phase-transition sweep reproduces the classic collapse of P(SAT) around
  clause/variable ratio ≈ 4.26 for random 3-SAT.

## Why this today

The earlier builds in this ledger were engines you *run* (a regex VM, a database,
a physics sim, an autodiff trainer). A SAT solver is an engine that *reasons* —
and uniquely, it can **prove itself honest**: a SAT answer is checkable by
substitution, an UNSAT answer by an independent proof checker. That made it
irresistible for a no-human-in-the-loop build: correctness isn't a matter of
eyeballing output, it's mechanically falsifiable, so the adversarial review and
the 1500-case differential gate actually mean something. It's also the universal
reduction target — one engine that solves Sudoku, coloring, and queens — which
makes for a genuinely fun, visual demo on top of a serious core.

## Where a human could take this next

- **Performance:** replace the linear-scan VSIDS pick with a real binary heap +
  `decreaseKey`; switch watch lists to blocking literals; move the hot loops to a
  C extension. Pure-Python caps practical instances at a few thousand variables.
- **Inprocessing:** add bounded variable elimination, subsumption, and
  self-subsuming resolution (the SatELite/CaDiCaL preprocessing that often
  dominates solve time).
- **Better restarts/learning:** Glucose-style LBD-driven restarts, chronological
  backtracking, and target-phase saving.
- **Beyond decision:** model counting (#SAT), MaxSAT, incremental solving with
  assumptions (the API that makes solvers usable as a library), and proof export
  in the standard binary DRAT format for `drat-trim`.
- **Visualizer:** animate the full search (decisions, propagations, backjumps,
  restarts) as a scrubbable timeline rather than a single conflict snapshot.

## Layout
```
resolvent/
  cnf.py        DIMACS parse/serialize + CNF model + builder
  solver.py     the CDCL engine (watched literals, 1-UIP, VSIDS, restarts, DB reduction)
  oracle.py     brute-force truth-table solver + model counter (ground truth)
  generate.py   seeded random k-SAT generation
  encoders.py   queens / sudoku / coloring / pigeonhole encoders + decoders
  proof.py      DRUP proof serialization + independent RUP checker
  viz.py        implication-graph -> self-contained HTML
  cli.py        the command-line interface
  demo.py       in-process end-to-end tour
tests/test_resolvent.py
demo.sh
PLAN.md  REVIEW.md
```

Pure Python 3 standard library. No third-party dependencies.
