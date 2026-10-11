# Delve — PLAN

## Concept
Delve is a **symbolic execution engine** for a small imperative language ("DelveLang"), built from scratch in
pure Python 3 (stdlib only). Instead of running a program on one input, Delve runs it on *all* inputs at once:
inputs are symbolic bit-vectors, every `if`/`while` forks the state and records a **path condition**, and a
constraint solver decides which paths are feasible. Each feasible path yields a concrete input that drives
execution down exactly that path — automatic test generation — and every reachable `assert` failure,
division by zero or signed overflow yields a **concrete counterexample**, which Delve re-executes in a
concrete interpreter to prove it is real.

There is no Z3 and no external solver: Delve ships its own **QF_BV decision procedure** — a hash-consed
term DAG with constant folding, a bit-blaster (adders, multipliers, dividers, barrel shifters, comparators)
Tseitin-encoded into CNF, and an **incremental CDCL SAT solver** (2-watched literals, 1-UIP learning,
VSIDS, phase saving, Luby restarts, assumptions) underneath.

## Why it's interesting
Symbolic execution (KLEE, angr, SAGE) is how real tools find deep bugs and auto-generate high-coverage tests,
and SMT solving is the engine inside. Building the whole stack — language, solver, executor, verifier — shows
how the layers fit together. Fixed-width machine-integer semantics (wraparound, signed compares, shifts)
make the bugs real rather than "mathematical-integer" fantasies.

## Architecture
```
 source ──► lang.py (lexer, parser, AST)
                │
        ┌───────┴────────┐
        ▼                ▼
   interp.py         symex.py ──► terms.py (hash-consed BV/bool terms + folding)
 (concrete, W-bit)    forks, path conds        │
        ▲             checks (assert/div0/ovf) ▼
        │                              bitblast.py ──► sat.py (incremental CDCL)
        └── replay & confirm witnesses ◄── models
 report.py (text + HTML), cli.py (analyze / run / tests / equiv / solve)
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | DelveLang front end + concrete W-bit interpreter (`input()`, `assert`, `assume`, `while`, `if`, ops with wraparound semantics, traps for div0) | **required** |
| 2 | Bit-vector SMT solver: term DAG, bit-blasting of + - * / % & \| ^ << >> signed/unsigned compares, incremental CDCL SAT with assumptions | **required** |
| 3 | Symbolic executor: path forking, path conditions, bounded loop unrolling, feasibility pruning, per-path concrete test-input generation | **required** |
| 4 | Bug finding: assertion violations, division by zero, signed overflow — each with a counterexample that is replayed in the concrete interpreter to confirm | **required** |
| 5 | Equivalence checker: `equiv a.dl b.dl` proves two programs return/behave identically for all inputs (up to loop bound) or gives a distinguishing input | stretch |
| 6 | Line/branch coverage report + self-contained HTML report with path table | stretch |
| 7 | Term simplifier (constant folding, algebraic identities) and solver query cache to cut SAT calls; stats output | stretch |
| 8 | `solve` mode: a tiny constraint REPL/CLI for raw bit-vector formulas | stretch |

## Done means
Every feature has a test; the demo script analyzes the bundled example programs (buggy and clean) and every
reported bug replays concretely.
