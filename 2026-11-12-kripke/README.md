# Kripke — a symbolic model checker

Kripke checks finite-state systems written in a small SMV-style language against **CTL**, **LTL** and
**invariant** specifications, using **binary decision diagrams** built from scratch in Rust (zero
dependencies). It decides properties over state spaces far too large to enumerate, honours **fairness**
constraints, and — when a property fails — prints a **shortest counterexample** or a **lasso** (prefix +
loop) including the free-input values taken at every step.

```
$ kripke examples/msi_buggy.smv
[FAIL] INVAR writer_excludes_readers: !(writers = 1 & readers > 0)
  counterexample (3 states):
    State 1 (initial)   c0 = I  c1 = I  c2 = I
    State 2             [inputs taken: who=2, op=read]    c2 = S
    State 3             [inputs taken: who=1, op=write]   c1 = M        <- c2 is still Shared: protocol bug
```

## Run it

```bash
cargo build --release
./target/release/kripke examples/peterson.smv            # check every spec in a file
./target/release/kripke examples/elevator_naive.smv --html report.html   # HTML report with trace tables
./verify.sh                                              # the whole gate (build, tests, demos, fuzz) -> ALL GREEN
```

Subcommands: `check` (default), `explicit` (cross-check against the independent oracle), `gen` (scalable
model families), `fuzz` (differential testing), `dot` (BDD → Graphviz), `sim` (random execution), `help`.
Options: `--reorder` (dynamic sifting), `--stutter` (deadlock self-loops), `--lax`, `--html FILE`,
`--full-traces`, `--stats`, `--quiet`. Exit status: 0 all hold · 1 a property fails · 2 bad input.

## The language

```
MODULE main
IVAR  who : 0..2;                       -- free input, chosen anew every step
VAR   pc : {idle, try, crit};  n : 0..65535;  flag : boolean;
DEFINE busy := pc != idle;
ASSIGN init(pc) := idle;
       next(pc) := case who = 0 & pc = idle : {idle, try};   -- sets = nondeterminism
                        pc = crit : idle;
                        TRUE : pc; esac;
       next(n)  := (n + 1) mod 65536;
INIT / INVAR / TRANS   expr             -- raw constraints (TRANS may mention next(x) and inputs)
FAIRNESS expr                           -- the fair paths visit expr infinitely often
SPEC     AG (try -> AF crit)            -- CTL: EX AX EF AF EG AG E[a U b] A[a U b]
LTLSPEC  G (try -> F crit)              -- LTL: X F G U R
INVARSPEC NAME safe := !(a & b)         -- plain invariant, shortest counterexample
```
Booleans, bounded integers (`+ - * / mod`, comparisons, `in`), enums, `case`, sets. Ranges up to 4096
values use guarded value tables; larger ranges use bit-vector circuits. Temporal prefix operators take a
comparison-level operand, so `AG x = 3` means `AG (x = 3)`. Reserved single letters: `E A X F G U R`.
Out-of-range assignments are compile errors (`--lax` turns them into disabled transitions).

## Features (all shipped)

Required
1. **BDD engine** — hash-consed unique table, ITE with computed table, ∃/∀, relational product, rename, satcount, mark-sweep GC, in-place level swap.
2. **SMV-style front end** — bool/range/enum variables, free inputs, sets, `case`, arithmetic, `DEFINE`, `INIT/INVAR/TRANS/ASSIGN`, did-you-mean errors with line/column carets.
3. **Reachability & invariants** — BFS frontiers, state counts, diameter, deadlock detection with a path to the deadlock, shortest `INVARSPEC` counterexamples.
4. **Fair CTL** — Emerson–Lei fixpoints, `EX/EU/EG` with fairness, witnesses and counterexamples including fair lassos (SCC-descent loop construction).

Stretch
5. **Dynamic reordering** — pair-preserving Rudell sifting (`--reorder`): a 16-bit comparator goes 196,748 → 206 BDD nodes.
6. **LTL** — tableau-product construction reduced to fair `EG`, lasso counterexamples.
7. **Independent explicit-state oracle** (own evaluator, Tarjan-SCC fair-EG) + **random differential testing**: 1000+ random models agree on every verdict, count and trace validity, under random reordering / GC-stress / stuttering.
8. **HTML report** (light/dark, responsive, trace tables with changed cells highlighted, reachability profile) and **DOT** export.
9. **Model generators** — dining philosophers (naive/fixed), token ring, counters, comparator, LFSR (reachable = 2^N − 1 proves maximal length).

Also: bit-vector integer arithmetic for big ranges, `--stutter` deadlock semantics, `sim`.

## Verification

`./verify.sh`: warnings-as-errors build, ~30 test functions (BDD ops vs truth tables, GC, swaps, sifting,
bit-vector circuits exhaustively, parser round-trips and error positions, known-answer examples,
differential fuzz), replay of every adversarial-review probe ([REVIEW.md](REVIEW.md)), oracle agreement on
all examples, generated-family demos, HTML check, and 1000 fresh fuzz seeds.

## Why this, today

The repo already had SAT/SMT, symbolic execution and hardware equivalence, but nothing with decision
diagrams or temporal logic. Model checking is where BDDs, fixpoints and logic meet, and the subtle parts
(fair-lasso counterexamples, GC-safe fixpoints, variable order) are exactly where toy implementations cut
corners — so it was a good place to be careful and to prove correctness with an oracle.

## Where a human could take this next

* Partitioned transition relations and early quantification (needed for 100+ state bits of asynchronous processes).
* Counterexample-guided abstraction, bounded model checking with the repo's CDCL solver for comparison, k-induction / IC3.
* SMV modules (instantiation, `process`), arrays, `for` unrolling; real-time / CTL* extensions.
* On-the-fly LTL with generalized Büchi automata instead of the tableau (fewer auxiliary variables).
* Symmetry reduction for the generated families; ZDDs for sparse sets.
* Fairness on input variables and per-spec fairness; witness minimisation.
