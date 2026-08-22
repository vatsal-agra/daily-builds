# Horn

A miniature Prolog-family logic-programming language, built entirely from
scratch: a real term parser, unification with an occurs check and
trail-based backtracking, an SLD-resolution engine with cut and
negation-as-failure, a standard library written *in* the language itself,
and an interactive HTML visualizer of the search tree that actually solves
your query.

```prolog
% append/3, the whole thing -- runs forwards, backwards, and every way
% between, for free, because unification doesn't care which argument is
% the "input":
append([], L, L).
append([H|T], L, [H|R]) :- append(T, L, R).
```

```
?- append(X, Y, [1,2,3]).
X = [], Y = [1, 2, 3].
X = [1], Y = [2, 3].
X = [1, 2], Y = [3].
X = [1, 2, 3], Y = [].
```

## Why this, today

This repo has built a lot of "language" artifacts before -- a bytecode VM
(Coil), a WebAssembly toolchain (Kiln), an x86-64 JIT compiler (Ember), a
Hindley-Milner type inferencer (Unify), a regex engine -- and every single
one of them is imperative or functional: give it an input, it computes a
deterministic output, one path through the code at a time. Horn is the
first genuinely *declarative, relational* language in the repo's history.
A Horn program has no "next statement to run." Solving a goal means
searching a tree of possible resolutions, backtracking through a trail of
undone variable bindings whenever a branch fails -- and that search *is*
the algorithm, not an implementation detail hiding behind it. Building it
also meant confronting a different flavor of two ideas this repo has
touched before but never quite like this: "occurs check" here means
something structurally different from Unify's type-unifier (there,
unifying types once; here, unifying terms across an unbounded, backtracking
search tree), and the correctness oracle isn't "does it type-check" but
"does it find exactly the solution set logic predicts" -- checked against
four classics with independently known answers: a family-tree kinship
program, N-Queens, Australia map coloring, and Einstein's Zebra Puzzle
(exactly one of 5!x5!x5!x5!x5! naive possibilities satisfies all fifteen
clues; Horn finds it in under half a second).

## Quick start

```sh
cd 2026-08-22-horn
python3 -m horn query examples/family.horn "ancestor(tom, jim)."
python3 -m horn query examples/family.horn "grandparent(marge, X)." --all
python3 -m horn query examples/queens.horn "queens(8, Qs)."
python3 -m horn query examples/zebra.horn "water_drinker(X)."       # -> norwegian
python3 -m horn query examples/zebra.horn "zebra_owner(X)."         # -> japanese
python3 -m horn repl examples/family.horn                            # interactive top-level
python3 -m horn viz examples/family.horn -q "ancestor(tom, X)." -o trace.html  # open in a browser
```

### Running the tests

```sh
python3 -m horn test     # the pytest suite (or: python3 -m pytest tests)
python3 -m horn demo     # a narrated, assertion-checked walkthrough
./demo.sh                # everything above, end-to-end, through the real CLI
```

## Feature list

**Required (all four demonstrably work end-to-end):**

1. **Term parser** (`horn/lexer.py`, `horn/parser.py`) -- a real
   operator-precedence (Pratt) parser for a Prolog-subset syntax: atoms,
   variables, integers/floats, compound terms, `[H|T]` list syntax,
   `%`/`/* */` comments, quoted atoms, and the standard operator table
   (`:-`, `,`, arithmetic/comparison operators, `\+`, `!`), with the
   classic "arguments parse at precedence 999" trick that tells a
   comma-as-separator apart from comma-as-conjunction with no extra
   bookkeeping.
2. **Unification** (`horn/unify.py`) -- structural unification over
   first-order terms with an optional occurs check, and a trail (not
   substitution-copying) so backtracking undoes exactly the bindings a
   choice point made, in O(bindings-made) time.
3. **SLD-resolution engine** (`horn/engine.py`) -- `solve()` is one
   recursive generator implementing the whole search: backtracking, cut
   (`!`, correctly scoped -- commits the current clause and everything
   decided to its left in the same body, without leaking into the caller),
   and negation-as-failure (`\+`, cut-opaque, binds nothing on success).
4. **Builtins + a Horn-native standard library** (`horn/builtins.py`,
   `horn/stdlib.horn`) -- native unification/arithmetic/comparison/
   type-checking/`findall`/I-O, plus `append`, `member`, `length`,
   `reverse`, `permutation`, `select`, `nth0`/`nth1` (genuinely
   bidirectional -- search for an index *or* an element), `numlist`,
   `max_list`/`min_list`, `nextto`/`adjacent`, all written as ordinary
   Horn clauses, demonstrated by solving four classic problems with their
   full, correct, independently-verifiable solution sets.

**Stretch (both shipped):**

1. **An interactive HTML SLD-resolution-tree visualizer** (`horn viz`) --
   click to expand/collapse, color-coded success/fail, dark/light-theme
   aware, self-contained (no CDN, no build step). Runs its own compact
   tracing evaluator rather than instrumenting the reviewed engine
   directly, so `tests/test_viz.py` differentially checks it finds the
   *exact same* solutions, in the same order, as the real engine for every
   example -- and that check, plus an actual headless-Chromium render,
   caught three real bugs during development (see REVIEW.md #7-#9).
2. **A REPL** (`horn repl`) -- `consult`, `;`-to-retry / `.`-to-stop
   multi-solution stepping, a `trace` toggle, a persistent session
   database, and a visible prompt.

## Architecture

```
horn/
  terms.py      Atom, Var, Number, Compound; lists are the classic './2'
                 cons-cell encoding, not a separate type
  lexer.py       tokenizer
  parser.py      operator-precedence parser -> a loaded clause database
  unify.py       unification + trail-based bind/undo
  engine.py      Database, CutBarrier, solve() -- the resolution engine
  builtins.py    native predicates (=, is, comparisons, findall, I/O, ...)
  arith.py       arithmetic expression evaluator for is/2
  stdlib.horn    list/logic predicates, written in Horn itself
  runstack.py    runs a query in a big-OS-stack thread so deep recursion
                 fails cleanly instead of segfaulting
  repl.py        the interactive top-level
  viz.py         SLD-tree tracer + self-contained HTML renderer
  cli.py         `horn run/query/repl/viz/demo/test`
  demo.py        the `horn demo` walkthrough
examples/        family.horn, queens.horn, map_coloring.horn, zebra.horn
tests/           95 pytest tests: unifier, parser, engine, builtins,
                 the four example programs (against known answers), the
                 visualizer (differential + real-browser), the CLI
                 (subprocess-driven), and one regression test per
                 REVIEW.md finding
demo.sh          end-to-end verification through the real CLI
```

## Adversarial review

Nine real, concrete bugs were found and fixed across Phases 3-5 -- a stack
overflow on long-list queries (before the query ever reached the engine's
own deep-recursion safety net), a stdlib predicate that raised instead of
searching when asked "backwards," a cyclic-term print crash, a crash on
any file containing a directive, a malformed query silently truncated
instead of rejected, an unbounded per-query memory leak in long-lived
sessions, an unenforced cap in the visualizer, a stale-binding display bug,
and a real headless-Chromium JS crash the generated page's own source
didn't reveal by inspection. Full writeup, including what was checked and
found *correct*, in [REVIEW.md](REVIEW.md).

## Known, disclosed limitations

- **No `;` (disjunction) or `->` (if-then-else).** Cut is transparent
  through disjunction in real Prolog -- a real interaction to get right --
  and every demo/stdlib predicate that would want it is written instead as
  multiple clauses with a cut or an arithmetic guard. Left out rather than
  shipped half-right; using `;` is a clean syntax error, not silently wrong
  behavior.
- **No `assert`/`retract`.** The clause database is populated by
  `consult_text` and immutable for an `Engine`'s lifetime.
- **Deep non-tail recursion has a real, measured ceiling** (~10,000 nested
  Horn calls, via a dedicated big-OS-stack thread in `runstack.py`) --
  documented and enforced to fail with a clean `RecursionError`, not a
  segfault (confirmed: naively raising Python's recursion limit alone
  segfaults around 5,000 calls on the default thread stack).
- **The REPL's "end of clause" detection is a literal scan for `.` per
  line**, not a full tokenizer pass -- a `.` inside a quoted atom on the
  same line would be misread. No example or stdlib file does this, and
  `parse_single_term`'s trailing-input check guarantees this can only ever
  produce a clear syntax error, never a silently wrong answer.

## Where a human could take this next

- **`;`/`->` and a real cut-transparency implementation** -- the natural
  next step once disjunction is worth the added complexity.
- **`assert`/`retract`** for a dynamic database -- would turn Horn from a
  pure query engine into something that can model changing state (a
  simple game, a small expert system).
- **First-argument indexing** -- real Prolog systems skip clauses whose
  first argument obviously can't unify without even trying; would speed up
  predicates like `member/2` over long lists and make bigger CSPs (a full
  Zebra-puzzle SLD-tree, not just the answer) practical to visualize.
- **DCGs (Definite Clause Grammars)** -- Prolog's own parser-combinator
  sublanguage, translating naturally onto the term/unification machinery
  already here.
- **A WAM-style bytecode compiler** -- Horn's `solve()` is a
  tree-walking interpreter; compiling clauses to a real Warren Abstract
  Machine instruction set (this repo already has two bytecode VMs and a
  JIT compiler to borrow encoding/dispatch lessons from) would be the
  next order-of-magnitude in performance, the same way Ember (2026-07-29)
  went from Coil's bytecode VM to real machine code.
