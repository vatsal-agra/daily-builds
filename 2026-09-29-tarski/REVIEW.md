# Adversarial review (Phase 3)

Method: differential fuzzing (400 random stratified programs: naive vs semi-naive vs an *independent*
brute-force oracle in `fuzz_test.go` that enumerates every variable assignment), then hostile hand-driven
attacks on the CLI/REPL with malformed, degenerate and non-terminating programs.

## Findings (all fixed)
| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| 1 | `n(0). n(X) :- n(Y), X = Y + 1.` never terminates (arithmetic makes the Herbrand base infinite) and would eat all memory | High | Derived-fact budget (`-limit`, default 500k) aborts with an explanatory error (~1.3s) |
| 2 | Runtime error inside a `?-` query (e.g. `/ 0`) aborted the whole run, skipped later queries, and rendered as `?(Z) :- a(Z)...` with a nonsense line number | Medium | Query errors print, the rest continue, exit code 1; query pseudo-rule prints as `?- ...` |
| 3 | REPL `:why` before the program evaluated dereferenced a nil engine (panic) | Medium | Guarded with an error message |
| 4 | Query with a typo'd predicate silently answered "no answers" because the query registered the predicate's arity | Medium | Queries no longer create predicates; unknown predicate is an error. Rule bodies using never-defined predicates get a stderr warning |
| 5 | `why` on a densely shared derivation could print an exponentially large tree | Low | Output capped at 2000 lines with a truncation note |
| 6 | Error wording `1 arguments` | Low | `argument(s)` |
| 7 | Fuzz generator produced unstratifiable programs; engine correctly rejected them (not an engine bug) | – | Generator skips them, test asserts ≥50% still exercised |

## Verified non-issues
- Semi-naive == naive == oracle on 357 stratifiable random programs (mutual recursion, repeated body predicates, negation, comparisons, constants).
- Wildcards in negation (`not e(_, X)`) are existential, as intended.
- Cyclic data (ring graph) yields finite, acyclic proof trees (first derivation only references earlier tuples).

## Known, documented limitations (not bugs)
- Aggregates group by the remaining head variables; an empty group produces no row (`count(*)` over nothing yields no fact rather than 0).
- Aggregates range over *distinct body solutions* (Soufflé semantics), so `sum(S)` over two equal salaries of different people counts both.
- Ordering comparisons across types order integers before strings.
