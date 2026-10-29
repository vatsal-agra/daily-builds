# Argus — an explicit-state model checker for concurrent systems

Describe a concurrent system (processes, shared variables, channels, locks, protocols) in a small
modelling language. Argus **exhaustively explores every interleaving** and either proves your
properties or hands back a **shortest counterexample** — and then *independently re-executes that
counterexample from scratch* so you never have to take its word for it.

Pure Python 3 standard library. No dependencies. ~3k lines of checker, ~800 lines of tests, 17 models.

```
$ python3 -m argus check models/philosophers.arg
✗ safety (assertions, deadlock, runtime errors, forks_ok): VIOLATED — 20 states, 28 transitions, depth 3, 0.00s

✗ deadlock
  counterexample: 3 steps

  #  process  statement
  0  init   fork=[0,0,0] eating=0  |  Phil0@L14(i=0 l=0 r=1) Phil1@L14(i=1 l=1 r=2) Phil2@L14(i=2 l=2 r=0)
  1  Phil0  atomic { await fork[l] == 0; fork[l] = 1 }  (philosophers.arg:14)
            ↳ fork[0]: 0 → 1
  2  Phil1  atomic { await fork[l] == 0; fork[l] = 1 }  (philosophers.arg:14)
            ↳ fork[1]: 0 → 1
  3  Phil2  atomic { await fork[l] == 0; fork[l] = 1 }  (philosophers.arg:14)
            ↳ fork[2]: 0 → 1

  final state: fork=[1,1,1] eating=0  |  Phil0@L15(i=0 l=0 r=1) Phil1@L15(i=1 l=1 r=2) Phil2@L15(i=2 l=2 r=0)
  independent replay ✓ replayed 3 steps from the initial state; every step is enabled and deterministic
                    ✓ final state has no enabled transition and some process is not at an end state
```

## Run it

```bash
python3 -m argus check models/peterson.arg                 # verify every property in a model
python3 -m argus check models/abp.arg --fair strong --fair-by edge
python3 -m argus check models/lost_update.arg --html report.html    # interactive step-through report
python3 -m argus verify models                             # run every `// expect:` annotation
./demo.sh                                                  # end-to-end demo + test suite (37 checks, all green)
python3 -m unittest discover -s tests -t .                 # 55 unit / fuzz tests
```

| command | what it does |
|---|---|
| `check MODEL` | invariants, assertions, deadlock, runtime errors, LTL properties. `--prop NAME` (repeatable) · `--all` every distinct violation · `--por` partial-order reduction · `--fair none\|weak\|strong` · `--fair-by proc\|edge` · `-D N=4` override a const · `--max-states` · `--json` · `--html FILE` · `--save-trace FILE` · `--color` |
| `info MODEL` | processes, locations, process-local statements, labels, properties |
| `sim MODEL` | random (`--seed`) or `--interactive` simulation, `--save` the run |
| `replay MODEL TRACE.json` | independently validate a saved trace (counterexample or simulation) |
| `buchi 'FORMULA'` | show the Büchi automaton of an LTL formula (`--negate`, `--dot`) |
| `graph MODEL` | Graphviz state graph (deadlocks red, end states green, frontier dashed) |
| `verify PATH…` | run the `// expect: <property|safety> <pass\|fail> [fair=…] [by=…] [kind=…] [D=N:3] [por=1]` lines in model files |

Exit codes: `0` all hold · `1` a property is violated · `2` bad model / usage / internal-validation failure · `3` inconclusive (state limit).

## The modelling language (a Promela / PlusCal cousin)

```c
const N = 2;                          // constants (override with -D N=3)
var flag[2] = 0;  var turn : 0..1 = 0;    // ints, arrays, optional ranges (overflow = runtime error)
chan q[3] of 2;                       // bounded FIFO of 2-field messages

proc P(me) {                          // parameterised process
    var other = 1 - me;               // locals (init may use params)
    loop {                            // loop / while / if-else / break
        flag[me] = 1;  turn = other;
        label try:                    // labels are observable: at(P0, try)
        await flag[other] == 0 || turn == me;     // blocks until true
        atomic { x = x + 1; y = x; }  // one indivisible step (optionally led by await/send/recv)
        either { send(q, 1, 2); } or { skip; }    // nondeterministic choice (guarded by first stmt)
        nondet v in 0..3;             // nondeterministic value
        assert x <= 1, "message";
        label end_idle: recv(q, a, b);            // end* labels = legitimate resting places
    }
}
run P(0);  run P(1) as second;        // instances (P0, second) ;  for i in 0..N-1 { run P(i); }

invariant mutex: crit <= 1;           // any expression; may use at(P0,lbl), P0.local, len/empty/full/head(q)
ltl live: [] (at(P0, try) -> <> at(P0, cs));      // [] <> X U R W ! && || -> <->   (also always/eventually/next/until/release)
```
Expressions are C-like (`&&` `||` `!` `?:` `<<` `&` `^` … with C precedence, truncating `/` and `%`).

## What's inside — features

**Core**
1. **Modelling language + compiler** — consts, ranged ints, arrays, multi-field bounded channels, parameterised processes, `for`-replication, `if/while/loop/break/either…or/atomic/await/nondet/assert/label`; each process instance is lowered to a control-flow graph whose edges carry Python closures *generated from the source*; states are flat tuples.
2. **Safety checker** — level-synchronous BFS ⇒ **shortest** counterexamples; invariants, assertions, deadlock (valid-end-state aware), runtime errors (OOB index, division by zero, range overflow, errors inside invariants); `--all` reports one trace per distinct violation; state limit gives *inconclusive*, never a silent pass.
3. **LTL liveness checker** — LTL parser (with arithmetic atoms), NNF, **Gerth–Peled–Vardi–Wolper tableau → generalized Büchi**, product with the system, iterative Tarjan SCCs, accepting-**lasso** extraction. Fairness: *none*, *weak* and *strong*, over whole processes or individual statements. Strong fairness uses SCC refinement (remove states where a starved class is enabled, recurse).
4. **Self-certifying traces** — step-by-step rendering with state diffs and source lines, JSON export, and an **independent replay validator**: re-executes the trace from the initial state with only the one-step successor function, re-checks the violation (for LTL: evaluates the formula *directly* on the lasso word with a second, unrelated evaluator, and re-checks fairness on the loop). A checker bug can't silently produce a bogus counterexample.

**Stretch**
5. **Partial-order reduction** — ample sets (process-local, invisible, BFS queue proviso). `por_demo.arg`: 6,859 → 59 states with the same verdict.
6. **Simulator** — seeded random / interactive stepping; saved runs replay through the validator.
7. **Graphviz + Büchi export** — `graph`, `buchi --dot`.
8. **`verify` regression runner** with embedded `// expect:` annotations; 17 models, 33 expectations.
9. **Interactive HTML report** — self-contained page: verdict cards, per-process swim-lane timeline with the repeating cycle shaded, step list, state panel with changed values highlighted, ←/→ keys, play/pause, light/dark.

## Model library (`models/`)

| model | shows |
|---|---|
| `peterson` | correct mutual exclusion; starvation-freedom (LTL) |
| `mutex_race`, `flag_deadlock` | check-then-act race ⇒ mutex violation; no tie-breaker ⇒ deadlock |
| `lost_update`, `lost_update_fixed` | classic non-atomic increment (assertion) and its atomic fix |
| `philosophers` | circular wait ⇒ 3-step deadlock; `-D N=4` works too |
| `philosophers_ordered` | no deadlock; starvation freedom **fails under weak, holds under strong** fairness |
| `fairness_ladder` | one property per rung: none ⇒ ✗, weak ⇒ ✓, strong ⇒ needed |
| `prodcons` | bounded FIFO channel, ordering assertion, delivery liveness |
| `abp` | alternating-bit protocol over lossy channels; delivery needs per-statement strong fairness |
| `bakery`, `bakery_broken` | Lamport's bakery (N=2/3, 74k states); removing the doorway breaks it |
| `twophase` | two-phase commit: atomic commit + termination |
| `leader_ring`, `leader_broken` | Chang–Roberts election; forwarding every id elects several leaders |
| `por_demo` | partial-order reduction showcase |
| `errors` | runtime-error reporting |

## How I know it's right (Phases 3 & 5)

* `REVIEW.md` — 14 findings from an adversarial pass (one critical: the Büchi translation silently dropped acceptance of `x U true`, which would have turned *violated* into *holds*), each fixed and regression-tested.
* **Fuzz vs. an oracle**: 400 random LTL formulas × random lasso words — the Büchi automaton must agree with direct LTL semantics, for both the formula and its negation.
* **Liveness soundness**: 150 random cyclic programs × random formulas × 3 fairness modes — an independent brute-force lasso enumerator must never find a fair violation that the checker misses.
* **POR vs. full search** on 250 random programs: identical violation kinds and property names, fewer states.
* **Trace validator mutation tests**: dropped / swapped / corrupted steps and bogus deadlock claims are all rejected.
* **Mutation testing of the checker itself** (see below).
* `demo.sh`: 37 end-to-end assertions over every feature.

**Mutation testing of the checker** (`tools/mutate.py`): nine plausible bugs were injected one at a time —
weak fairness ignored, strong-fairness refinement dropped, POR cycle proviso removed, POR reducing processes
that properties observe, Büchi `until`-acceptance dropped, `end*`-label rule removed, state limit silently ignored,
replay validator skipping its state comparison, replay validator skipping its fairness re-check — and **all nine are
caught by the unit + fuzz suite**. (Two of the POR mutants *survived* my first test suite; that gap is why
`PorTests` exists.) One more mutant — reordering states inside a BFS level — survives, correctly: it is
semantically equivalent, since level-synchronous BFS still yields shortest traces.

## Why I built this today

The repo already has a SAT solver, SQL engine, TCP stack, Raft simulator, symbolic executor and a Verilog
formal toolkit — but nothing that answers the question concurrency bugs actually pose: *"is there **any**
interleaving where this goes wrong?"* A model checker is where several earlier threads (automata, SCC
graph algorithms, DSL → bytecode compilation, reduction theory) meet, and it's one of the few tools where
"correct" is *checkable by construction* — so I made the checker prove its own counterexamples.

## Where a human could take this next

* **Symmetry reduction** (permute identical processes) and **bitstate hashing** to push past ~1M states; a compiled (C/Rust) successor function would give 50–100×.
* **Stutter-invariant POR for LTL** (the `X`-free fragment) so liveness benefits from reduction too, and **on-the-fly nested DFS** to find lassos without building the whole product.
* **Richer data**: bounded records, channel arrays (`chan c[N][k]`) and rendezvous (capacity-0) channels, so ring/tree protocols read more naturally; real time (clock variables) for timeout models.
* **Counterexample minimisation** for liveness lassos, and "explain" mode that points at the statement that *should* have been guarded.
* **Proof-producing mode**: emit an inductive-invariant certificate (or a BDD/SAT-based symbolic back-end for much larger bounded models).
* A **web playground**: the HTML report already embeds the trace viewer — add a model editor and run the checker via WASM/Pyodide.
* Translate models from real code (Go channels, `pthread`, TLA⁺/PlusCal import).

## Layout

```
argus/lang.py     lexer + parser (statements, expressions, LTL)
argus/model.py    compiler: AST → CFG → generated closures; successor function; state formatting
argus/safety.py   BFS safety checker + partial-order reduction
argus/ltl.py      LTL normal form, lasso evaluator, GPVW tableau → Büchi, DOT/text export
argus/live.py     product construction, Tarjan SCC, fair-cycle search (none/weak/strong), lasso extraction
argus/trace.py    trace model, rendering, JSON, independent replay validator
argus/report.py   interactive HTML report
argus/cli.py      command-line interface
models/*.arg      17 annotated models        tests/   55 unit + fuzz tests        demo.sh  end-to-end demo
```
