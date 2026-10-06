# Milner — PLAN

## Concept
A complete, statically typed ML-family language ("Milner ML") implemented from scratch in Go (stdlib only):
source → lexer → parser → **Hindley–Milner type inference** → **pattern-match exhaustiveness/redundancy analysis** → evaluator,
wrapped in a CLI / REPL with caret-annotated diagnostics.

Nothing in the repo so far is a *statically typed* language: Loom-style projects were dynamically typed VMs, Tarski is Datalog.
The interesting part is that the type system is real: let-polymorphism with level-based generalisation, the value restriction
(for `ref`), user algebraic data types, and Maranget-style usefulness checking that prints a concrete *witness* of the missing case.

## Why it's interesting
- Programs are never annotated, yet `let compose f g x = f (g x)` gets `('a -> 'b) -> ('c -> 'a) -> 'c -> 'b`.
- The checker rejects bad programs *before* running them, with errors that point at the offending span.
- Exhaustiveness is a classic algorithm (matrix specialisation/defaulting) that is easy to get subtly wrong → great adversarial-review target.

## Architecture
```
internal/syntax   lexer.go  ast.go  parser.go  diag.go (spans, caret rendering)
internal/types    types.go (TVar/TCon/TRow, levels)  unify.go  infer.go  print.go  trace.go
internal/check    exhaust.go  (Maranget usefulness: exhaustive? redundant arms? witness)
internal/eval     value.go  eval.go (TCO loop)  builtins.go  prelude.ml (embedded)
cmd/milner        main.go   run | check | type | explain | repl
examples/*.ml     gallery programs with .out golden files
```
Pipeline per top-level declaration: parse → infer (extends type env) → exhaustiveness warnings → eval (extends value env).

## Feature list
| # | Feature | Tier |
|---|---------|------|
| 1 | Lexer + parser for the full surface language (let/let rec/and, fun, if, match, tuples, lists, `::`, operators, annotations, `type` decls, comments) with positioned syntax errors | **required** |
| 2 | Hindley–Milner inference: let-polymorphism, level-based generalisation, occurs check, value restriction with weak vars, annotations, readable type printer, span-accurate type errors | **required** |
| 3 | Algebraic data types (parametric, recursive, mutually-recursive via one decl) + pattern matching (nested, or-patterns, as-patterns, literals, guards-free) with Maranget exhaustiveness + redundancy analysis and witnesses | **required** |
| 4 | Evaluator with proper tail calls, `let rec`/mutual recursion, refs, strings, builtins, an ML prelude written in Milner itself, runtime errors with stack-safety limit; CLI `run` / `check` / `type` and a REPL | **required** |
| 5 | Row-polymorphic records: `{x=1; y=2}`, `r.x`, `{r with x=3}`, inferred types like `{x : 'a; ..} -> 'a` | stretch |
| 6 | `explain`: step-by-step inference trace (instantiate, unify, generalise) for any expression | stretch |
| 7 | Typed holes `_` that report the type expected at that position (plus the in-scope bindings of matching type) | stretch |
| 8 | Gallery of ≥6 example programs with golden outputs (n-queens, expression simplifier, balanced tree, tiny stack VM, …) run in tests | stretch |

Plan: build 1–4 in Phase 2; stretch 5, 6, 7 (and 8) in Phase 4.
