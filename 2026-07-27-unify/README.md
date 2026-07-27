# Unify

A Hindley-Milner type inference engine, built from scratch in pure Python
(stdlib only — no dependencies).

**Status: Phase 3 (Adversarial review) complete.** Seven real bugs found
and fixed, including one that would have made the planned REPL hang —
see [REVIEW.md](REVIEW.md). See [PLAN.md](PLAN.md) for the concept and
architecture.

## Quick start

```bash
python3 -m unify.cli run examples/factorial.uy
python3 -m unify.cli check examples/polymorphism.uy --trace
python3 -m unify.cli check examples/type_error.uy   # see a real diagnostic
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

Run the test suite: `python3 -m unittest discover -s tests` (100 tests)

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

Next up: stretch features (Phase 4) — a server-backed HTML derivation-tree
visualizer and a REPL with a language-defined prelude.
