# Unify

A Hindley-Milner type inference engine, built from scratch in pure Python
(stdlib only — no dependencies). It's the algorithm behind ML, Haskell,
OCaml, and (in a descendant form) Rust's and TypeScript's inference: given
source code with **no type annotations at all**, it derives the single
most general type of every expression, catches type errors before a line
of it runs, and lets a function like `id` be used at `int` and at `bool`
in the same program without you ever writing a type down.

Full writeup of the concept and why it's interesting: [PLAN.md](PLAN.md).
Adversarial review (7 real bugs found and fixed, including one that would
have hung the REPL): [REVIEW.md](REVIEW.md).

## Why this, today

This repo's history is full of runtimes (chess engines, SAT solvers,
renderers, nine separate from-scratch transformer language models) and
data structures, but nothing that does *static analysis* — a pass over a
program that runs **before** the program does. Hindley-Milner type
inference is a compact, sharply-specified algorithm (a few hundred lines)
with unusually clean pass/fail ground truth: classic test cases like
`fun x -> x x` (must be rejected — infinite type) or `let id = fun x -> x
in (id 1, id true)` (must be accepted — `id` used polymorphically) give
unambiguous correctness criteria, the same way this repo's other builds
have leaned on perft counts, finite-difference gradient checks, or NIST
test vectors instead of "looks plausible."

## Quick start

```bash
python3 -m unify.cli run examples/factorial.uy
python3 -m unify.cli check examples/polymorphism.uy --trace
python3 -m unify.cli check examples/type_error.uy   # see a real diagnostic
python3 -m unify.cli repl                           # interactive REPL
python3 -m unify.cli web                            # visualizer at http://127.0.0.1:8765/
```

## Feature list

Four required, both stretch goals implemented (see PLAN.md for the
original commitments):

- **[required] Lexer + parser** (`unify/lexer.py`, `unify/parser.py`) for a
  small ML-like language: `let`/`let rec ... in`, `fun`, `if/then/else`,
  arithmetic/comparison/boolean operators, tuples, lists (`[]`/`::`),
  `Some`/`None`, and `match` pattern matching.
- **[required] Algorithm W type inference** (`unify/infer.py`,
  `unify/types.py`): unification with an occurs check (rejects infinite
  types), let-generalization for real polymorphism, and full
  derivation-tree tracing.
- **[required] Tree-walking evaluator** (`unify/evaluator.py`) that runs
  well-typed programs to real values, including genuine recursion, with
  short-circuit `&&`/`||`, clean errors for division by zero,
  non-exhaustive matches, and comparing function values.
- **[required] Precise diagnostics** (`unify/diagnostics.py`): every
  rejected program names the two conflicting types (with consistent
  "expected"/"found" wording and shared variable naming across both) and
  points a caret at the exact source span responsible. Missing files and
  stack-depth limits are reported the same way, not as raw Python
  tracebacks.
- **[stretch] REPL** (`unify/repl.py`, `python3 -m unify.cli repl`):
  persistent `let`-bindings across lines, full let-polymorphism across
  statements, `:type <expr>` to check a type without evaluating, `:env` to
  list every binding, and a small standard-library prelude
  (`map`/`filter`/`foldl`/`length`/`append`/`reverse`/`assoc`) written in
  Unify itself and type-checked/loaded at startup.
- **[stretch] Web visualizer** (`unify/web/`, `python3 -m unify.cli web`):
  a real `http.server` backend with zero client-side inference logic —
  type an expression in the browser, see its principal type, evaluated
  value, and the full Algorithm W derivation tree, all computed
  server-side in Python and rendered from JSON.

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
