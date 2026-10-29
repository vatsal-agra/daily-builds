# Argus — PLAN

## Concept
**Argus** is a from-scratch **explicit-state model checker** (in the spirit of SPIN / TLC) for concurrent
systems, written in pure-stdlib Python. You describe processes in a small Promela/PlusCal-flavoured
modelling language (shared variables, bounded channels, `atomic`, non-determinism, labels); Argus
exhaustively explores **every interleaving** and either proves your properties or hands back a
**shortest counterexample** as a readable, step-by-step trace.

## Why it's interesting
Concurrency bugs are the ones tests never find. A model checker is the tool that does — and building
one touches automata theory (LTL → Büchi via the Gerth–Peled–Vardi–Wolper tableau), graph algorithms
(BFS, Tarjan SCC, fair-cycle detection), compilers (a DSL lowered to a control-flow graph and then
to generated Python), and reduction theory (partial-order reduction with ample sets). No earlier
entry in this repo does temporal-logic verification of concurrent programs.

## Architecture
```
 model.arg ──► lang.py (lexer/parser → AST)
              │
              ▼
          model.py  (AST → per-process CFG → generated Python closures; flat tuple states)
              │
     ┌────────┴──────────┐
     ▼                   ▼
  safety.py            live.py  ◄── ltl.py (LTL parse/NNF, GPVW tableau → generalized Büchi,
 BFS: invariants,       product × system, Tarjan SCC,         lasso evaluator)
 assertions, deadlock,  weak/strong fairness refinement,
 runtime errors, POR    lasso extraction
     │                   │
     └────────┬──────────┘
              ▼
          trace.py  (render, JSON, **independent replay validator**: re-executes the trace from
                     the initial state and re-checks the violation, incl. LTL on the lasso word)
              ▼
          cli.py  (check / sim / replay / buchi / graph / verify / info)
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **Modelling language + compiler**: consts, int vars with ranges, arrays, bounded multi-field channels, parameterised procs, `run`/`for`-replication, `if/while/loop/break/either…or/atomic/await/nondet/assert/label`, compiled to CFG + generated closures | **required** |
| 2 | **Safety checker**: level-synchronous BFS over the full interleaving space; invariants, assertions, deadlock (with `end*` labels as valid end states), runtime errors (OOB, div-by-0, range); *shortest* counterexample; `--all` collects one per violation | **required** |
| 3 | **LTL liveness checker**: LTL parser, NNF, GPVW tableau → generalized Büchi, product with the system, Tarjan SCC, accepting-lasso search under *none / weak / strong* fairness (per process or per statement) | **required** |
| 4 | **Trace engine**: step-by-step rendering with state diffs, JSON export, and an **independent replay validator** that re-executes every counterexample from scratch (and evaluates the LTL formula directly on the lasso word) so verdicts are self-certifying | **required** |
| 5 | **Partial-order reduction** (ample sets: local-only processes, invisibility, BFS queue proviso) for safety checking, with state-count stats | stretch |
| 6 | **Random / interactive simulator** (`sim`) with seeds and replay of saved traces | stretch |
| 7 | **Graphviz export** of state graphs and Büchi automata (`graph`, `buchi`) | stretch |
| 8 | **Model library + `verify` regression runner** with embedded `// expect:` annotations (Peterson, broken Peterson, Dekker-ish, bakery, dining philosophers, alternating-bit protocol, 2PC, lost-update race…) | stretch |

## Verification strategy
* Büchi translation fuzzed against a direct lasso-word LTL evaluator (random formulas × random words).
* POR verdicts compared with full search across the model library.
* Every counterexample produced anywhere in the test suite is pushed through the replay validator.
