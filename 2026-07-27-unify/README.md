# Unify

A Hindley-Milner type inference engine, built from scratch in pure Python
(stdlib only — no dependencies).

**Status: Phase 5 (Verification) complete.** 119 unit tests and a 34-check
end-to-end demo (`demo.py`) all pass. See [PLAN.md](PLAN.md) for the concept
and architecture, [REVIEW.md](REVIEW.md) for the adversarial review.

## Quick start

```bash
python3 -m unify.cli run examples/factorial.uy
python3 -m unify.cli check examples/polymorphism.uy --trace
python3 -m unify.cli check examples/type_error.uy   # see a real diagnostic
python3 -m unify.cli repl                           # interactive REPL
python3 -m unify.cli web                            # visualizer at http://127.0.0.1:8765/
```

## What works right now

- **Lexer + parser** (`unify/lexer.py`, `unify/parser.py`) for a small
  ML-like language: `let`/`let rec ... in`, `fun`, `if/then/else`,
  arithmetic/comparison/boolean operators, tuples, lists (`[]`/`::`),
  `Some`/`None`, and `match` pattern matching.
- **Algorithm W type inference** (`unify/infer.py`, `unify/types.py`):
  unification with an occurs check (rejects infinite types), let-generalization
  for real polymorphism, and full derivation-tree tracing.
- **Tree-walking evaluator** (`unify/evaluator.py`) that runs well-typed
  programs to real values, including genuine recursion, with short-circuit
  `&&`/`||`, clean errors for division by zero, non-exhaustive matches, and
  comparing function values.
- **Precise diagnostics** (`unify/diagnostics.py`): every rejected program
  names the two conflicting types (with consistent "expected"/"found"
  wording and shared variable naming across both) and points a caret at
  the exact source span responsible. Missing files and stack-depth limits
  are reported the same way, not as raw Python tracebacks.
- **REPL** (`unify/repl.py`, `python3 -m unify.cli repl`): persistent
  `let`-bindings across lines, full let-polymorphism across statements,
  `:type <expr>` to check a type without evaluating, `:env` to list every
  binding, and a small standard-library prelude (`map`/`filter`/`foldl`/
  `length`/`append`/`reverse`/`assoc`) written in Unify itself and
  type-checked/loaded at startup.
- **Web visualizer** (`unify/web/`, `python3 -m unify.cli web`): a real
  `http.server` backend with zero client-side inference logic — type an
  expression in the browser, see its principal type, evaluated value, and
  the full Algorithm W derivation tree, all computed server-side in
  Python and rendered from JSON.

Run the test suite: `python3 -m unittest discover -s tests` (119 tests)

Run the end-to-end verification demo: `python3 demo.py` (34 checks covering
every required and stretch feature against real assertions, not just
"didn't crash" — includes spinning up the actual web server and hitting it
over real HTTP).

## The language

```
let [rec] name [params] = expr in body     -- binding (curried params)
fun x y -> expr                            -- lambda (curried)
if cond then a else b
match expr with | pattern -> expr | ...    -- patterns: _, x, 1, true,
                                            --   (a, b), [], h :: t, Some p, None
(a, b, ...)                                -- tuples
[a, b, c]                                  -- list literal (sugar for a :: b :: c :: [])
Some expr | None                           -- option
+ - * / = <> < > <= >= && ||                -- operators (arithmetic is int-only)
```

No unit type, no type annotations (they're inferred), no mutual recursion
(`and`), no type classes — see PLAN.md's "Non-goals" for why.

## Sharp edges (documented, not bugs)

Two parsing behaviors are the same well-known ambiguities every ML-family
language (OCaml, F#, SML) has, for the same reason — "fixing" them would
mean deviating from how these languages actually parse, not correcting a
defect. See `REVIEW.md` for the full writeup.

- `f -1` parses as `f - 1` (subtraction). Write `f (-1)` to apply `f` to a
  negative literal.
- A `match`/`if`/`fun` used as a non-final `match` case's body greedily
  extends as far right as possible, so it can swallow the following
  `| pattern -> ...` arms meant for the *enclosing* match. Parenthesize the
  inner construct: `| p -> (match ...)`.

## Where a human could take this next

- Type classes / an `Ord` constraint, so comparison operators stop being a
  runtime check and become a real typeclass-resolved feature.
- User-defined algebraic data types (`type tree = Leaf | Node of tree * int * tree`)
  instead of the fixed `Some`/`None`/tuple/list vocabulary.
- Match exhaustiveness and redundancy checking (today, a non-exhaustive
  match type-checks and only fails at runtime).
- Mutual recursion (`let rec f = ... and g = ...`).
- A bytecode VM instead of the tree-walking evaluator, for real recursion
  depth without leaning on Python's own call stack.
