# Horn — a logic-programming language built from scratch

## Concept

A miniature Prolog-family logic-programming language and interpreter, built
entirely from scratch in pure Python: a real term parser for a Prolog-subset
syntax, unification with an occurs check, a trail-based SLD-resolution engine
(backtracking search over Horn clauses — the paradigm's namesake), cut (`!`)
and negation-as-failure (`\+`), and a small standard library of list/arithmetic
predicates bootstrapped *in Horn itself*.

Where most programs say "compute the answer," a logic program says "here are
the facts and rules; find every assignment that makes the goal true." The
engine doesn't execute a fixed sequence of steps — it searches a tree of
possible resolutions, backtracking through a trail of variable bindings
whenever a branch fails, exploring only enough of the tree to find (or
exhaust) solutions. That search *is* the interesting algorithm here: it is
one Python generator function using structured backtracking, not print-driven
control flow — the same shape as the real WAM-less interpreters Prolog
implementations bootstrap from.

## Why it's interesting

This repo has built many "language" artifacts — a bytecode VM (Coil), a WASM
toolchain (Kiln), a JIT compiler (Ember), a Hindley-Milner type inferencer
(Unify), a regex engine — but every one of them is imperative or functional:
given input, compute a deterministic output. Horn is the first genuinely
*declarative, relational* language in the repo: a Horn-clause program has no
notion of "the next statement to run." Solving `append(X, Y, [1,2,3])` finds
every way to split a list — Horn's `append/3`, itself written in three lines
of Horn, runs forwards, backwards, and every way between, for free, purely
because unification doesn't care which argument is the "input." Building the
resolution engine also means confronting a genuinely different flavor of
"occurs check" and "renaming apart" than Unify's type-inference unifier
(there, unifying types; here, unifying first-order terms across an unbounded
search tree with backtracking), and a different kind of correctness oracle:
not "does it type-check" but "does it find exactly the solution set logic
predicts," checked against classics with known, enumerable answers (family
trees, N-Queens, map coloring, the Zebra puzzle).

## Architecture

```
horn/
  terms.py       Term representation: Atom, Var, Number, Compound, PList sugar
  lexer.py       Tokenizer for the Prolog-subset syntax
  parser.py      Operator-precedence term parser -> facts/rules/queries (clause DB)
  unify.py       Unification with occurs check + a trail (list of bound Vars)
                 for O(1) undo on backtrack, instead of copying substitutions
  engine.py      SLD-resolution solver: solve(goal, depth) is a Python
                 generator; renaming-apart per clause instantiation; cut (!)
                 implemented as a barrier exception scoped to the enclosing
                 clause body; \+ (negation as failure) as a sub-solve probe
  builtins.py    Native predicates: unification (=/2, ==/2), arithmetic
                 (is/2, </2, >/2, =</2, >=/2, =:=/2, =\=/2), type checks
                 (var/1, nonvar/1, atom/1, number/1, is_list/1), findall/3,
                 write/1, nl/0, halt
  stdlib.horn    List/logic predicates written IN Horn: append/3, member/2,
                 length/2, reverse/2, nth0/3, last/2, not_equal via \+
  repl.py        Interactive REPL: consult a .horn file, run queries,
                 `;` for next solution, `.` to stop, trace toggle
  cli.py         `horn run file.horn`, `horn repl`, `horn trace query.horn`,
                 `horn viz`, `horn demo`
  viz.py         Builds a JSON resolution trace during solve(); renders it
                 to a self-contained interactive HTML SLD-tree
  examples/      family.horn, queens.horn, zebra.horn, map_coloring.horn
  tests/         test_unify.py, test_engine.py, test_builtins.py,
                 test_parser.py, test_examples.py
  demo.sh        Exercises every feature end-to-end through the real CLI
```

## Feature list

### Required (core, must work end-to-end)
1. **Term parser** — full Prolog-subset syntax: atoms, variables (capitalized
   / `_`), integers, compound terms `f(a, b)`, lists `[1,2,3]` and
   `[H|T]` cons syntax, operators (`,` conjunction, `;` disjunction, `:-`
   rule/directive, `!` cut, comparison/arithmetic operators), `%` line
   comments, facts and rules loaded into a clause database indexed by
   functor/arity.
2. **Unification with occurs check and trail-based backtracking** — a real
   unifier over first-order terms (compound structural unification, list
   unification via the same compound machinery) with an occurs check flag
   (rejecting `X = f(X)`), and a trail (stack of bound `Var` objects) that
   lets the engine undo exactly the bindings made since a choice point in
   O(bindings-since) time instead of copying/restoring whole substitution
   maps.
3. **SLD-resolution engine with backtracking, cut, and negation-as-failure**
   — `solve(goal)` as a generator yielding one solution (a binding snapshot)
   per success and resuming search on `next()`; clause renaming-apart per
   call so recursive calls never capture variables; cut (`!`) that prunes
   remaining alternatives for the current call *and* any choice points
   created since entering the clause body it appears in (verified against
   the standard "cut commits to this clause and everything already decided
   left of the cut in the body" semantics); `\+ Goal` negation-as-failure
   implemented as a bindings-preserving sub-solve that succeeds iff the
   sub-solve has zero solutions.
4. **Built-in predicate library + a Horn-native standard library** — native
   built-ins for unification/arithmetic/comparison/type-checking/`findall/3`,
   plus `stdlib.horn` list predicates (`append/3`, `member/2`, `length/2`,
   `reverse/2`, `nth0/3`, `last/2`) written *as Horn clauses*, demonstrated
   solving four classic logic-programming problems end-to-end with their
   full, correct solution sets: a family-tree kinship program, N-Queens,
   map coloring, and the Zebra puzzle (Einstein's riddle).

### Stretch
1. **Interactive HTML SLD resolution-tree visualizer** — collects a
   structured trace during `solve()` (goal entered, clause tried, unification
   bindings, success/fail/cut/backtrack events) and renders it as a
   self-contained, dependency-free HTML page: a collapsible/zoomable search
   tree with play/step/scrub controls, color-coded success/fail/cut/pruned
   branches, and the live variable bindings shown per edge — dark/light theme
   aware, screenshot-verified in headless Chromium (same pattern as this
   repo's other visualizers).
2. **REPL** — `horn repl` with `consult(file)`, interactive queries,
   `;`-to-retry-for-next-solution / `.`-to-stop multi-solution stepping (the
   real Prolog top-level UX), a `trace` toggle that prints each resolution
   step live, and persistent database state across queries in one session.

## Correctness strategy

Every builtin/list predicate gets a differential/property check against a
brute-force Python oracle where one is easy to write (e.g. `append/3`'s
solution set vs. Python's own list-splitting; `member/2` vs. `in`). The four
demo puzzles have independently-known-correct answers (N-Queens solution
counts for small N are published; the Zebra puzzle has exactly one solution)
— those are used as hard ground truth, not "it produced *something*."
