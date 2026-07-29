# Phase 3 — Adversarial Review

Hostile-reviewer pass over the Phase 2 build, looking specifically for the
failure modes a JIT compiler is most likely to have: encoder bugs that
look right on the happy path, calling-convention edge cases, and
inconsistencies between the interpreter and the JIT that a shallow test
battery wouldn't surface. Four real bugs found and fixed; one real,
disclosed (not "fixed") limitation documented with measurements.

## Bugs found and fixed

### 1. CRITICAL — interpreter and JIT disagreed on whether a program is even valid

```
fn f(x) {
    if (x > 100) {
        y = 5;     // y was never declared
    }
    return x;
}
```

Calling `f(1)` (so the `if` branch is never taken): the **interpreter**
returned `1` — Python only ever walks the taken branch, so it never
evaluates the bad assignment and never notices anything is wrong. The
**JIT** raised `EmberRuntimeError: undefined variable 'y'` — codegen has
to emit machine code for every statement in the function body, including
branches that never execute, so it hits the invalid assignment
unconditionally at compile time.

Two backends that disagree about whether a program is even *valid*,
depending on which one you asked, is a worse failure than either one
computing a wrong number — it means the language has no single semantics.
Found by deliberately probing exactly this asymmetry (control-flow-gated
validity vs. eager whole-body codegen) rather than by any test in the
existing battery failing.

**Fix:** added `ember/semcheck.py`, a static check pass both the
interpreter and the JIT run *before* doing anything else. It walks every
function's full body unconditionally (independent of runtime control
flow) and requires that every variable read or plain-assigned is a
parameter or `let`-declared *somewhere* in the function — exactly
matching the flat-namespace rule `codegen_x64._collect_locals` already
implements, just checked eagerly instead of being discovered lazily by
whichever backend happens to walk that branch. Now both backends raise
the identical clean error for the identical program.

### 2. Two duplicate-defined functions crashed with a raw `AssertionError`

```
fn foo(x) { return x; }
fn foo(x) { return x + 1; }
```

The interpreter silently let the second definition clobber the first in
its `{name: fn}` dict (no error at all — a real correctness bug on its
own). The JIT crashed with `AssertionError: label 'fn__foo' defined
twice` from deep inside the assembler's label bookkeeping — a raw
assertion, not a clean `EmberRuntimeError`, and not something a CLI user
should ever see.

**Fix:** `semcheck.check_program` now rejects a duplicate function name
up front, for both backends, with a clean, line-numbered error.

### 3. Calling an undefined function crashed the JIT with a raw `KeyError`

```
fn f(x) { return g(x); }
```

The interpreter already raised a clean `EmberRuntimeError` (it looks up
`g` in its function dict at call time). The JIT compiled the `call`
instruction against an unresolvable label and only found out when
`Assembler.resolve()` tried to patch it — surfacing as
`KeyError: "undefined label 'fn__g'"`, an internal implementation detail
leaking straight to the user.

**Fix:** covered by the same `semcheck` pass, which validates every call
target exists (and now also that its argument count matches — see below)
before either backend does anything, so this is structurally impossible
to reach anymore rather than caught reactively in two different places
with two different error shapes.

### 4. A pathologically deep expression crashed both backends with a raw `RecursionError`

A left-associative chain of 3,000 `+` operators (`1 + 1 + 1 + ... + 1`)
parses fine (the parser's precedence-climbing loop is iterative) but
produces a 3,000-deep left-leaning AST. Both the interpreter's evaluator
and the codegen's expression walk recurse into `.left`, so both hit
Python's default recursion limit (1000) and crashed with a raw
`RecursionError` — again, not a clean Ember error, and (unlike bugs 1-3)
the two backends *did* at least agree with each other, but "crashes the
same way" isn't the same as "handled".

**Fix:** `semcheck` now also enforces a maximum statement/expression
nesting depth (400, checked incrementally so the checker itself never
recurses past ~401 frames doing the checking) and raises one clean,
explanatory `EmberRuntimeError` instead. Verified this doesn't produce
false positives on realistic code: a function with 1,000 *sequential*
(non-nested) `let` statements — depth stays at 2 the whole time, since
sequential siblings don't add nesting — still compiles and runs
correctly (checked against both backends).

### 5. Bonus (not a bug, but a real coverage gap): the 5th/6th call-argument marshalling path was never exercised

`examples/args6.em`'s `weighted_sum` (6 parameters) was only ever
invoked as a *top-level* entry point directly from Python/the CLI —
which only exercises the **prologue's** param-to-stack-slot spill for
r8/r9, never the **call site's** `pop r8` / `pop r9` argument-marshalling
path (only reachable when one *compiled Ember function* calls another
with 5+ arguments). Added `call_weighted_sum(x)` to `args6.em`, which
calls `weighted_sum` with computed (not bare-variable) arguments,
specifically to force that path — verified correct against the
interpreter and gcc oracles (280 for all three on `call_weighted_sum(10)`).
This is exactly the kind of gap a coverage-blind test battery can hide:
every existing test passed, and the bug class (wrong REX.B handling on a
`pop r8`/`pop r9` in the call path specifically) simply had no test that
could have caught it.

## A real, disclosed (not "fixed") limitation: native stack overflow

Ember has no stack-depth guard and no tail-call optimization. A deeply,
non-tail-recursive JIT'd function eventually overflows the real OS call
stack and the process receives `SIGSEGV` — uncatchable, since it isn't
a Python exception at all.

Measured on this box (default 8 MiB thread stack, `count(n)` a
single-`int64`-local, non-tail-recursive function):

| recursion depth | JIT result |
|---|---|
| 100,000 | returns correctly |
| 200,000 | segfault |
| 1,000,000 / 2,000,000 | segfault |

**This is not an Ember-specific defect.** The equivalent C function,
compiled with the box's real `gcc -O0` (no optimizations, matching
Ember's own non-optimizing codegen), segfaults at the exact same kind of
depth for the exact same reason — verified directly: `count(2000000)`
compiled by real `gcc -O0` also exits via `SIGSEGV`. Fixing this for real
would mean either a guard-page-based stack-overflow trap (what Go's
runtime and the JVM do) or a growable/segmented stack — legitimate
techniques, but a different, much larger project than a one-day
from-scratch JIT. Documented here and in the README rather than silently
left for a user to discover, and rather than "fixed" with an artificial
recursion-depth cap that no real native compiler enforces either.

## Gate check

After all four fixes, re-ran the full differential battery
(`ember demo`: 29 cases across every example program, plus the division
guard tests, the benchmark, and the objdump oracle) — all green — and
manually re-verified all five numbered findings above no longer
reproduce (each one now raises the identical clean error from both
backends, checked directly, not just inferred from the suite passing).
