# Unify

A Hindley-Milner type inference engine, built from scratch in pure Python
(stdlib only — no dependencies).

**Status: Phase 2 (Core build) complete.** All four required features work
end-to-end. See [PLAN.md](PLAN.md) for the concept and architecture.

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
  programs to real values, including genuine recursion.
- **Precise diagnostics** (`unify/diagnostics.py`): every rejected program
  names the two conflicting types and points a caret at the exact source
  span responsible.

Run the test suite: `python3 -m unittest discover -s tests`

Next up: adversarial review (Phase 3), then the stretch features — a
server-backed HTML derivation-tree visualizer and a REPL with a
language-defined prelude (Phase 4).
