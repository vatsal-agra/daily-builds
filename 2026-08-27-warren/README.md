# Warren

A from-scratch Prolog implementation that compiles clauses to real
[Warren Abstract Machine](https://en.wikipedia.org/wiki/Warren_Abstract_Machine)
(WAM) instructions and executes them on a tagged-heap register machine —
the same execution model behind SWI-Prolog, GNU Prolog, and SICStus.

**Status: Phase 4 (stretch + polish) complete.** All 4 required features
plus both stretch features are done: the parser, the WAM compiler +
abstract machine, the built-in predicate library, the golden-model
differential oracle, an interactive HTML WAM execution-trace visualizer
(`warren viz`), and DCG (`-->`) support with a real arithmetic-expression
grammar example. 82 tests green. See `PLAN.md` for the
architecture/feature list and `REVIEW.md` for the adversarial review (10
real bugs found and fixed, most of them genuine WAM choice-point/
register-lifetime bugs caught only by the golden-model oracle
disagreeing with the compiled answer).

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
