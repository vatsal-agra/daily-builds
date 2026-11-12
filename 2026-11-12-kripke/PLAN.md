# Kripke — Plan

## Concept
**Kripke** is a from-scratch **symbolic model checker** in Rust (zero dependencies). You describe a
finite-state system in a small SMV-style language (booleans, bounded integers, enums, nondeterminism,
free inputs, `case`, `TRANS`/`INIT`/`INVAR`, `next(x) := ...`) and ask questions in CTL, LTL, or as
invariants. Kripke compiles the system into **binary decision diagrams**, computes the reachable state
space as a fixpoint, decides every property — with **fairness** constraints — and, when a property
fails, prints a **shortest counterexample trace** or a **lasso** (prefix + loop) for liveness failures.

It is the repo's first *formal-verification / BDD* build (earlier verification work was SAT/SMT/
symbolic-execution/hardware-equivalence; none used decision diagrams or temporal logic).

## Why it is interesting
* BDDs let you reason about 10^20+ states without enumerating them; the whole thing is "just" a hash-consed
  DAG + a handful of fixpoint equations — a beautiful algorithm-meets-logic combination.
* Counterexample extraction for liveness (fair `EG` lassos, Emerson–Lei fixpoint) is the subtle part
  most toy checkers skip.
* Variable ordering is the make-or-break of BDDs; the build includes real dynamic **sifting** so the
  effect is observable (e.g. a 2n-bit comparator: exponential vs linear).
* An **independent explicit-state checker** (separate evaluator over concrete states) cross-checks the
  symbolic one on randomly generated models, so correctness is demonstrated, not asserted.

## Architecture
```
 source ──lexer/parser──► AST ──┬─► compile (model.rs) ─► BDD engine (bdd.rs)
                                │        init / trans / invar / fairness / specs as BDDs
                                │              │
                                │        reach + invariants (check.rs)   CTL + fairness (ctl.rs)
                                │              │                              │
                                │        traces (trace.rs): shortest path, fair lasso witnesses
                                │              │
                                │        LTL → tableau product → fair-EG (ltl.rs)
                                └─► explicit.rs : independent concrete-state evaluator + CTL (oracle)
                                       report.rs: terminal + self-contained HTML report
                                       gen.rs: scalable model families (philosophers, token ring, …)
```
* `bdd.rs` — unique table, ITE with computed table, ∃/∀/relational product (`and_exists`), rename,
  satcount, pick-one, mark-sweep GC with free list, adjacent-level swap, block **sifting**.
* Integer/enum values are *guarded value tables* `[(value, BDD guard)]` (union semantics, so `{a,b}`
  sets give nondeterminism for free).
* Current/next-state variables are interleaved in the order so relational products stay small.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | BDD engine: hash-consing, ITE, quantification, relprod, rename, satcount, GC | **required** |
| 2 | SMV-style language front end → symbolic transition system (bool/range/enum vars, free inputs, nondeterministic sets, `case`, arithmetic, `DEFINE`, `INIT/INVAR/TRANS`, `ASSIGN`) with positioned errors | **required** |
| 3 | Symbolic reachability, state counting, deadlock detection, `INVARSPEC` with shortest counterexample trace | **required** |
| 4 | CTL model checking with `FAIRNESS` (Emerson–Lei), witnesses/counterexamples incl. fair lasso for `EG`/`AF` | **required** |
| 5 | Dynamic variable reordering: pair-preserving block sifting + `--reorder` flag + stats | stretch |
| 6 | LTL (`LTLSPEC`) via tableau-product construction reduced to fair `EG`, with lasso counterexamples | stretch |
| 7 | Independent explicit-state engine + randomized differential testing vs symbolic | stretch |
| 8 | Self-contained HTML report (verdicts, highlighted trace tables, BDD stats) + DOT export | stretch |
| 9 | Scalable model generators (dining philosophers, token ring, bakery-lite, counters) | stretch |

Required = 1–4. Stretch = 5–9 (aim: all that fit).
