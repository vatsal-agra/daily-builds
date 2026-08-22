# Horn

A miniature Prolog-family logic-programming language, built entirely from
scratch: a term parser for a real Prolog-subset syntax, unification with an
occurs check and trail-based backtracking, an SLD-resolution engine with cut
and negation-as-failure, and a standard library of list/logic predicates
written in Horn itself.

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end (see below). Adversarial review, stretch features, and the test
suite are still to come.

## Quick start

```sh
cd 2026-08-22-horn
python3 -m horn query examples/family.horn "ancestor(tom, jim)."
python3 -m horn query examples/family.horn "grandparent(marge, X)." --all
python3 -m horn query examples/queens.horn "queens(8, Qs)."
python3 -m horn query examples/zebra.horn "water_drinker(X)."
python3 -m horn repl examples/family.horn
```

## What's implemented so far

- **Parser** (`horn/lexer.py`, `horn/parser.py`) -- a real operator-precedence
  parser for a Prolog-subset syntax: atoms, variables, integers/floats,
  compound terms, `[H|T]` list syntax, `%`/`/* */` comments, and the usual
  operator table (`:-`, `,`, arithmetic/comparison operators, `\+`, `!`).
- **Unification** (`horn/unify.py`) -- structural unification over first-order
  terms with an optional occurs check, and a trail (not substitution-copying)
  for backtracking.
- **SLD-resolution engine** (`horn/engine.py`) -- `solve()` is a single
  recursive generator implementing backtracking search, cut (`!`), and
  negation-as-failure (`\+`).
- **Builtins + Horn-native stdlib** (`horn/builtins.py`, `horn/stdlib.horn`) --
  native `=`/`is`/comparisons/`findall`/type-checks/I-O, plus `append`,
  `member`, `length`, `reverse`, `permutation`, `numlist`, and more, written
  as ordinary Horn clauses.
- Four classic demos in `examples/`: a family-tree kinship program, N-Queens,
  Australia map coloring, and Einstein's Zebra Puzzle -- all solved correctly
  (verified against known answers: 4 solutions for 6-Queens, the Zebra
  puzzle's unique "Norwegian drinks water / Japanese owns the zebra").
- Deep-recursion safety: queries run in a dedicated thread with a large OS
  stack (`horn/runstack.py`), so pathologically deep recursion fails cleanly
  with an error instead of crashing the process.

## Coming next

Adversarial review (Phase 3), stretch features -- an interactive HTML
SLD-resolution-tree visualizer and REPL polish (Phase 4), a full test suite
(Phase 5), and final packaging (Phase 6). See [PLAN.md](PLAN.md).
