# Warren

A from-scratch Prolog implementation that compiles clauses to real
[Warren Abstract Machine](https://en.wikipedia.org/wiki/Warren_Abstract_Machine)
(WAM) instructions and executes them on a tagged-heap register machine —
the same execution model behind SWI-Prolog, GNU Prolog, and SICStus.

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end: the parser, the WAM compiler + abstract machine, the built-in
predicate library, and the golden-model differential oracle (65
tests, including a full solution-for-solution cross-check between the
compiled WAM and the independent tree-walking interpreter across N-Queens,
the Zebra puzzle, cut, if-then-else, negation, catch/throw, assert/retract,
and DCG grammars). See `PLAN.md` for the full architecture and feature
list.

## Quick start

```
python3 -m warren run examples/family.pl "ancestor(tom, X)." --all
python3 -m warren run examples/queens.pl "count_solutions(6, C)."
python3 -m warren run examples/zebra.pl "zebra(Owner, WaterDrinker, Street)."
python3 -m warren repl examples/family.pl
python3 -m warren test
```

## Why this, today

See `PLAN.md`'s "Why it's interesting" section — in short: this repo has
built interpreters, bytecode VMs, a JIT, a type inferencer, and a CPU
pipeline simulator, but never *logic programming*, a genuinely different
execution paradigm (SLD resolution + unification + backtracking instead of
direct evaluation), and never a term-graph heap with REF/STR-tagged cells
and trail-based backtracking.

## Layout (planned)

```
warren/          the implementation package
tests/           unit + differential test suite
examples/        .pl programs used as demos and test fixtures
PLAN.md          architecture + feature list
REVIEW.md        adversarial self-review (written in Phase 3)
```

Run instructions, full feature list, and "where to take this next" will be
filled in during Phase 6.
