# Warren

A from-scratch Prolog implementation that compiles clauses to real
[Warren Abstract Machine](https://en.wikipedia.org/wiki/Warren_Abstract_Machine)
(WAM) instructions and executes them on a tagged-heap register machine —
the same execution model behind SWI-Prolog, GNU Prolog, and SICStus.

**Status: Phase 1 (plan) complete.** See `PLAN.md` for the full
architecture and feature list. Implementation starts in Phase 2.

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
