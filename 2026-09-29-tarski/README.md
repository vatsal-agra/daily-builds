# Tarski

A from-scratch **Datalog engine** in Go (standard library only): text program → parser → safety check →
predicate dependency graph → Tarjan-SCC **stratification** → **semi-naive** bottom-up evaluation to the least
fixpoint, with **proof-tree provenance** for every derived fact. Named for Tarski's fixed-point theorem.

## Run it
```sh
go build -o tarski .
./tarski run examples/family.dl              # answers every `?-` query in the file
./tarski run -stats -naive examples/graph.dl # compare evaluation strategies
./tarski why examples/family.dl 'ancestor(alice, gina)'   # proof tree
./tarski check examples/access.dl            # validate + show strata
./tarski bench -n 100                        # naive vs semi-naive on generated graphs
./tarski repl examples/pointsto.dl           # interactive
./demo.sh                                    # builds + exercises every feature (18 checks)
go test ./...                                # unit suite + oracle fuzzing
```
Flags for `run`: `-naive`, `-stats`, `-dump` (print all relations), `-limit N` (derived-fact budget, default 500000).

## Language
```prolog
parent(alice, bob).                                   % facts
ancestor(X, Y) :- parent(X, Y).                       % rules (recursion, mutual recursion)
ancestor(X, Z) :- parent(X, Y), ancestor(Y, Z).
childless(P)  :- person(P), not has_child(P).         % stratified negation (`_` is existential inside `not`)
generation(C, N) :- generation(P, M), parent(P, C), N = M + 1.   % arithmetic: + - * / mod, comparisons = != < <= > >=
size(D, count(*)) :- emp(_, D, _).                    % aggregates: count(*) count(X) sum(X) min(X) max(X)
?- ancestor(alice, X), X != bob.                      % queries (conjunctive, may use comparisons/negation)
```
Constants: integers, lowercase symbols, `"strings"`. Variables: Uppercase or `_x`; `_` is anonymous. Comments: `%`, `//`, `/* */`.

## Features
1. **Parser** with line:col errors and a source snippet + caret; error recovery is "stop at first error", never a panic.
2. **Semi-naive evaluation** (per-stratum delta ranges over append-only relations, hash indexes on bound columns, greedy join ordering); mutual recursion and non-linear rules included.
3. **Stratified negation** and safety (range-restriction) checks; unstratifiable programs are rejected with the offending cycle (`p -> not r -> p`).
4. **Built-ins, queries, provenance**: arithmetic/comparison literals (including `X = expr` binding), ad-hoc `?-` queries, and `why` proof trees (each fact remembers its first derivation, so proofs are finite even on cyclic data).
5. **Aggregates** (`count`, `sum`, `min`, `max`) stratified like negation; recursion through an aggregate is rejected.
6. **Naive evaluator + `bench`**: same engine with delta-tracking off; `bench` verifies both compute the identical model and reports iteration/probe/time counts (semi-naive does ~50–65× fewer join probes on a 100-node chain/ring).
7. **REPL** with `:why`, `:facts`, `:strata`, `:program`, `:reset`; a statement that breaks the program is rolled back.
8. Runaway-recursion guard (`n(X) :- n(Y), X = Y + 1.` is cut off with an explanation instead of eating memory).

## Verification
- `go test ./...`: parser, recursion, negation, stratification, safety, arithmetic, aggregates, provenance, REPL, CLI — plus a **differential fuzzer** that generates ~400 random stratified programs and checks naive == semi-naive == an independent brute-force oracle (enumerates all variable assignments, shares no join code).
- `demo.sh`: 18 end-to-end checks. See `REVIEW.md` for the adversarial review (7 findings, all fixed).

## Why this today
The repo has SAT solvers, a SQL engine, a type inferencer, CRDTs, but no *deductive database*. Datalog is the
smallest language where recursion and relational joins meet, and it has unusually good ground truth (a
fixpoint semantics, an easy brute-force oracle, and naive-vs-semi-naive equivalence) so "does it work" is checkable, not vibes.

## Where a human could take this next
- **Magic-set / demand-driven evaluation** so `?- path(a, X)` doesn't compute the whole closure.
- **Incremental maintenance** (DRed): add/remove facts and update the model without recomputing.
- Well-founded semantics (unrestricted negation), lattice aggregation inside recursion (shortest paths), and a cost-based join planner.
- Persisted relations / CSV loading (`.input`/`.output` à la Soufflé) and a compiled (code-generating) backend.
