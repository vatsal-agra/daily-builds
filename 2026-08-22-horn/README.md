# Horn

A miniature Prolog-family logic-programming language, built entirely from
scratch: a term parser for a real Prolog-subset syntax, unification with an
occurs check and trail-based backtracking, an SLD-resolution engine with cut
and negation-as-failure, and a standard library of list/logic predicates
written in Horn itself.

**Status: Phase 4 (stretch + polish) complete.** All 4 required features
work end-to-end and have survived a hostile-reviewer pass -- see
[REVIEW.md](REVIEW.md). **Both** planned stretch features are shipped:

- **An interactive HTML SLD-resolution-tree visualizer** (`horn viz`) --
  click-to-expand/collapse search tree, color-coded success/fail/cut,
  dark/light-theme-aware, screenshot-verified in real headless Chromium. Its
  own tracing evaluator is checked to find the *exact same* solutions, in
  the same order, as the real engine (a differential test, not just "it
  produces a picture") -- and that check caught two real bugs during
  development: an unenforced solution cap and stale variable bindings
  leaking into the page's own title. See REVIEW.md for the writeup and
  `tests/test_viz.py` for the differential check itself.
- **A REPL** (`horn repl`) with `consult`, `;`-to-retry / `.`-to-stop
  multi-solution stepping, a `trace` toggle, and a persistent session
  database -- built during core development and hardened further here (a
  visible prompt, a fixed memory leak on abandoned queries, and a rejected
  rather than silently-mangled malformed query).

**Status: Phase 5 (verification) complete.** 95 pytest tests, an
assertion-checked `horn demo` walkthrough of every feature, and
`./demo.sh` -- an end-to-end script driving the real CLI (not the Python
API) through every example, the REPL, and the visualizer -- all green.
Fixing `demo.sh` to actually catch its own real failure (it initially
grepped for text the page doesn't contain, so it silently "passed" a step
that hadn't actually been checked) is itself documented as part of getting
this phase to a genuine, not just superficial, green.

Final packaging (Phase 6) is still to come.

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
