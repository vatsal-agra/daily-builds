# Unify — a Hindley-Milner type inference engine, from scratch

## Concept

Every prior build in this repo's history that touches "type" or "language"
(Coil's bytecode VM, RegexLab's automata, the nine Loom transformers) skips
the one thing that makes a *statically-typed* functional language possible:
**type inference**. No source annotations, and yet the compiler derives the
single most general ("principal") type of every expression, catches type
errors before a single line runs, and lets polymorphic functions like `id`
be used at `int` and at `bool` in the same program without the programmer
ever writing a type.

That's Hindley-Milner-Damas: the algorithm behind ML, Haskell, OCaml, F#,
and (in a descendant form) Rust's and TypeScript's inference. It's a genuine
gap in this repo's history — every other "from scratch" build has been a
runtime (VM, chess engine, SAT solver, renderer) or a data structure. This
is the first to build a *static analysis* that runs before the program does.

## Why it's interesting

- It's a real algorithm with sharp, checkable correctness criteria: does it
  accept every program a human would consider well-typed, reject every
  program that isn't, and infer types *at least as general* as the most
  specific correct type (principality)? Classic HM test cases (`fun x -> x
  x` must be rejected as an infinite type; `let id = fun x -> x in (id 1,
  id true)` must be accepted with `id` used polymorphically) give
  unambiguous pass/fail ground truth, the same way Faraday's RC time
  constants or Cotangent's finite-difference checks did for prior builds.
- Unification with an occurs check, generalization/instantiation of type
  schemes, and a substitution-threading inference algorithm are compact but
  deep — the entire engine is a few hundred lines, but getting it *right*
  (as opposed to "looks right on the demo cases") is the actual challenge,
  which is exactly the kind of project this repo has consistently chosen.
- It naturally produces a good visualizer: the inference *derivation tree*
  (each subexpression annotated with the type judgment used to derive it,
  and the substitution that resulted) is a genuinely interesting object to
  render, distinct from every previous visualizer in this repo (automaton
  threads, attention heatmaps, implication graphs, commit graphs).

## Architecture

```
source text
   |  lexer.py      -> tokens
   v
   parser.py        -> AST (Pratt/recursive-descent: let, let rec, fun,
   |                    application, if, arithmetic/comparison, tuples,
   |                    lists (cons/nil), and a small variant/ADT form with
   |                    pattern matching: Some/None, Cons/Nil-style)
   v
   infer.py         -> Algorithm W: fresh type variables, a Substitution
   |                    (finite map var->type, composable), unify() with
   |                    an occurs check, generalize()/instantiate() for
   |                    let-polymorphism, producing a principal Type and a
   |                    full derivation trace (list of judgment nodes)
   v
   eval.py          -> tree-walking evaluator over the *same* AST (only
   |                    runs if inference succeeded — a well-typed program
   |                    cannot go wrong, so the evaluator has no type
   |                    dispatch/casts, only value-shape pattern matching)
   v
   cli.py           -> `unify run file.uy`, `unify repl`, `unify check`
   web/server.py    -> stdlib http.server backend serving an interactive
                        browser page: type an expression, see its inferred
                        type AND the full derivation tree AND the evaluated
                        result, all computed server-side (zero client-side
                        inference logic, same pattern as this repo's
                        Gambit/Formulate/Trove server-backed UIs)
```

## Feature list

**Required (core, must work end-to-end):**

1. **Lexer + parser** for a small ML-like expression language: integers,
   booleans, strings, `let`/`let rec ... in`, `fun x -> e` (curried
   multi-arg via nested funs), function application, `if/then/else`,
   arithmetic (`+ - * /`), comparisons (`= < >`), tuples `(a, b)`, lists
   (`[]`, `::`), and `match` pattern matching over lists/tuples/variants.
2. **Algorithm W type inference** — fresh type-variable generation,
   `Substitution` composition, `unify()` with an occurs check (rejects
   infinite types like `fun x -> x x`), `generalize()`/`instantiate()`
   implementing let-polymorphism, and a full built-in environment (`+ :
   int -> int -> int`, list/tuple constructors, etc.) — producing the
   principal type of any accepted expression, or a precise type error
   (expected vs. found, with source location) for a rejected one.
3. **Tree-walking evaluator** that actually runs well-typed programs to a
   real value (int/bool/string/closure/tuple/list/variant), including
   genuine recursion (`let rec fact n = if n = 0 then 1 else n * fact (n -
   1) in fact 10` must evaluate to `3628800`) and genuine higher-order use
   of polymorphic bindings.
4. **Type-error diagnostics that are actually useful** — every rejection
   names the two types that failed to unify, the source span of the
   offending subexpression, and (for occurs-check failures) explicitly
   says "infinite type" rather than a generic unification failure.

**Stretch (2+, implement at least 1 fully):**

5. Interactive derivation-tree **HTML visualizer**, server-backed (stdlib
   `http.server`, no client-side inference): paste/pick an expression, see
   the AST, the full Algorithm W judgment tree (each node's inferred type
   and the substitution it contributed), the final principal type, and the
   evaluated result, all in one page.
6. A **REPL** (`unify repl`) with persistent `let`-bindings across lines,
   `:type <expr>` to show inferred type without evaluating, and a small
   standard prelude (`map`, `filter`, `foldl` over lists) defined *in the
   language itself* and type-checked/loaded at startup — proof the
   inference engine handles real, nontrivial, mutually-referencing
   polymorphic code, not just the toy examples from the test suite.

## Non-goals

No type classes / traits, no full ADT declarations with user-defined
constructors beyond a small fixed set (Some/None, Cons/Nil, tuples) — HM
plus let-polymorphism plus a fixed variant vocabulary is already a complete,
honest scope for one day, and matches this repo's pattern of picking one
algorithm and implementing it for real rather than a broad, shallow toolkit.
