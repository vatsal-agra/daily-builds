# Tarski — PLAN

## Concept
A from-scratch **Datalog engine** in Go (stdlib only): text program -> parser -> safety check ->
dependency graph + stratification -> **semi-naive bottom-up evaluation** to a least fixpoint
(named for Tarski's fixed-point theorem, which guarantees it exists and is unique for monotone rules).
Every derived fact carries **provenance**, so `why(fact)` prints a real proof tree.

## Why interesting
Repo has SAT solvers, a type inferencer, a SQL engine, but no *logic programming / deductive database*.
Datalog is where recursion (transitive closure, reachability, points-to analysis) meets relational joins.
Correctness has strong ground truth: semi-naive must derive exactly the same facts as naive evaluation
(an in-repo oracle), and stratified negation must reject non-stratifiable programs (`p :- not q. q :- not p.`).

## Architecture
- `lexer.go`, `parser.go` — tokens, recursive-descent parser -> AST (`ast.go`)
- `check.go` — range-restriction/safety checking, arity consistency
- `strata.go` — predicate dependency graph, Tarjan SCC, negation/aggregation cycle detection, stratum order
- `eval.go` — relations with hash indexes, join planning by binding order, naive and semi-naive evaluators
- `prov.go` — provenance store + proof-tree rendering
- `query.go` — ad-hoc `?-` queries with variable bindings
- `main.go` — CLI: `run`, `repl`, `bench`, `check`

## Features
1. **REQUIRED** Parser for facts, rules, queries, comments, strings/ints/atoms/variables/`_`, with line:col errors.
2. **REQUIRED** Semi-naive evaluation of recursive rules (incl. mutual recursion, multi-atom delta rules) to fixpoint.
3. **REQUIRED** Stratified negation (`not p(X)`) + safety checks + rejection of unstratifiable programs with the offending cycle.
4. **REQUIRED** Built-in comparisons and arithmetic (`X < Y`, `Z = X + Y*2`, `!=`) plus `?-` queries and proof-tree provenance (`why`).
5. STRETCH Aggregates in heads (`count`, `sum`, `min`, `max`) stratified like negation.
6. STRETCH Naive evaluator + `bench` mode comparing rule-firings/time, and equivalence check against semi-naive.
7. STRETCH Interactive REPL (assert facts/rules, query, `why`, `:explain` strata).
