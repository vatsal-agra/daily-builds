# Adversarial Review

Two rounds: bugs found and fixed *during* Phase 2 core build (while
getting the WAM's choice-point machinery correct in the first place),
and a fresh hostile pass in Phase 3 specifically hunting for what
survived. All of the below are real, reproduced, root-caused, and fixed
(with a regression test), not hypothetical.

## Round 1 — found while building the WAM (Phase 2)

These surfaced from directly testing nondeterministic/meta-predicate
programs (`select/3` chained twice, `permutation/2`, N-Queens, the Zebra
puzzle, `catch/3`) against the golden-model oracle, and are the reason
the oracle exists at all: every one of them is a case where the WAM's
compiled answer silently diverged from the obviously-correct
tree-walking interpreter, not a crash.

1. **A choice point's saved continuation was captured one line too
   early.** `_do_call` computed `ret` (the return address after `call`)
   and only *afterwards* set `self.CP = ret` — but the choice point
   pushed for a multi-clause predicate captured `self.CP` *before* that
   assignment, i.e. the caller's *pre-call* CP, not the shared
   continuation every candidate clause should return to. Symptom: two
   chained calls to a nondeterministic predicate (`select(X,L,R),
   select(Y,R,_)`) looped forever, `choice_stack` growing without
   bound, because backtracking into the second call's alternatives
   silently re-executed the first call instead of returning to it.
   Fixed by capturing the choice point's saved CP as the post-call
   return address (every candidate clause for one call site shares one
   continuation), mirroring `meta_call`'s own setup.

2. **No last-call optimization meant a fact-only clause with a real
   body call had no environment to save/restore CP around it.** A
   clause with zero permanent variables and no cut was compiled with no
   `allocate`/`deallocate` at all — but if its body still issued a
   `call` (e.g. a synthetic wrapper clause whose whole body is one
   call), that `call` unconditionally overwrites `self.CP` for its own
   callee's return, and nothing restores it before the clause's own
   final `proceed`. Symptom: a one-instruction infinite loop —
   `count(0)` alone hung forever, `self.P` fixed pointing at its own
   `proceed`. Fixed: any clause whose body issues at least one call now
   always gets an environment (a deliberate step back from textbook
   last-call optimization, documented in `compiler.py`).

3. **`\+`, `catch/3`, and friends leaked choice points when abandoned
   early.** `meta_call`'s cleanup only ran the loop body's own
   `backtrack()`/undo — but a caller that takes one solution and stops
   (`\+`, `catch/3`'s exception path) closes the generator instead,
   which skips straight to `finally`, which never trimmed
   `choice_stack`. Symptom: `IndexError: list index out of range` deep
   inside an unrelated later call, because a *stale* choice point (with
   `heap_mark` pointing past heap cells `\+`'s own cleanup had already
   truncated) got retried. Fixed by trimming `choice_stack` back to the
   call's own entry barrier in `finally`, unconditionally.

4. **The same swap-registers-only-at-generator-boundaries design broke
   any caller that keeps running between solutions.** `meta_call` saved
   the caller's P/CE/CP once at entry and restored them once at exit —
   but `catch/3`'s recovery goal *yields* a solution and the caller
   (`_call_builtin`) then runs *more of its own instructions* before
   ever asking for a second one. Between those, the caller was running
   with the sub-computation's dead P/CE/CP still installed. Symptom:
   `TypeError: list indices must be integers, not NoneType` — `self.CE`
   was `None` where a live environment frame was expected. Fixed by
   swapping the caller's registers back in around *every* yield, not
   just generator entry/exit.

5. **A defensively-pushed retry choice point could re-enter its own
   still-running Python generator.** Every builtin call got wrapped in
   a choice point that retries by calling `next()` on its generator —
   but a meta-predicate like `catch/3` runs *real compiled code*
   through `meta_call`, which leaves *its own* genuine choice points on
   the (shared, global) stack — pushed chronologically *after* the
   wrapper existed conceptually but appended *above* it in practice.
   Backtracking into those inner choice points before the outer
   wrapper's own `try_next()` call had returned re-entered the same
   generator frame. Symptom: `ValueError: generator already executing`.
   Fixed: only wrap a builtin in a retry choice point when its own
   execution left `choice_stack` exactly as it found it (a "simple"
   builtin, e.g. `between/3`); a meta-predicate's own nested choice
   points ARE its retry mechanism.

6. **Fixing #5 introduced its own bug: an un-wrapped generator becomes
   unreachable.** Skip the wrapper choice point and nothing holds a
   reference to that generator any more — CPython's refcounting GC
   closes it *immediately* when `_call_builtin` returns, and closing a
   suspended `meta_call` generator runs its `finally`, which restores
   P/CE/CP to what *they* were when *that* generator started —
   silently clobbering the value `_call_builtin` had just set. Symptom:
   `existence_error` for a predicate that was never called by the
   program (`catch/3` re-running from a stale saved P landed back on
   its own `call catch/3` instruction, which re-ran the *whole thing*
   including now trying to call the atom `caught` as a goal). Fixed by
   keeping a reference to any such generator for the machine's
   lifetime (`Machine._keepalive`) — a small, bounded, and disclosed
   memory cost, not a correctness compromise.

7. **`query()` yielded live references into the mutable binding graph,
   not snapshots.** Both engines' `query()` did `deref(v)` and yielded
   the result directly — correct only if the caller inspects it *before*
   the generator is resumed or exhausted, since backtracking
   destructively unbinds Vars in place. `list(engine.query_text(...))`
   — used throughout this project's own test suite and CLI `--all`
   flag — collects every solution *then* lets the generator finish,
   by which point the earliest answers' still-unbound nested variables
   had already been reset. Symptom: `append([1,2],[3,4],X)` printed as
   `[_H|_R]` — the clause's own now-unbound pattern variables — instead
   of `[1,2,3,4]`. Fixed by `copy_term`-snapshotting each solution at
   yield time in both engines.

## Round 2 — fresh adversarial pass (Phase 3)

8. **`==`/`compare`/`sort` didn't distinguish `1` from `1.0`.**
   `order.compare_terms` compared `Num` values with plain `==`, so
   `1 == 1.0` (which must be false — `==`/2 is structural identity, not
   arithmetic equality; that's `=:=`) came back true, and `sort/2`
   could silently drop a float as a "duplicate" of its equal-valued
   int. Fixed: equal-valued Nums of different Python type (`int` vs
   `float`) now compare as *distinct*, with the ISO tie-break (float
   sorts before the same-valued int).

9. **The CLI printed raw Python tracebacks for entirely ordinary user
   mistakes** — a missing file, a syntax error in the consulted
   program. Fixed: `cli.py` now catches `FileNotFoundError`,
   `ParseError`/`LexError`, and `RecursionError` at the point they can
   occur and reports a one-line `warren: ...` message instead;
   genuinely unexpected internal errors still surface with their real
   traceback (deliberately — silently swallowing an actual Warren bug
   would be worse).

10. **A several-thousand-element list could blow Python's recursion
    limit.** Several of the parser/golden-WAM bridge functions
    (`term_vars`, `copy_term`, `unify`, `heap_unify`, `reify`,
    `push_term_cached`, `unify_heap_with_term`, the pretty-printer) walk
    a term with plain Python recursion — one frame per list cell, since
    Prolog lists are right-nested cons cells — so a long (but
    completely ordinary) list could raise `RecursionError` well within
    normal-sized data (reproduced at 5,000 elements). This is a real
    architectural gap relative to a textbook WAM, whose own "recursion"
    for this is just heap-address arithmetic with no Python call stack
    involved — disclosed rather than silently worked around: fixing it
    properly means rewriting those bridge functions iteratively (a
    scope cut for today, noted below), not something a config value
    alone can fix. Mitigated two ways rather than left broken: (a)
    `warren/__init__.py` raises Python's own recursion limit — CPython
    3.12+ (confirmed on this box) has an independent C-stack-proximity
    check that raises a *clean* `RecursionError` rather than
    segfaulting even with the limit set very high, so this is safe, not
    just "probably fine"; (b) `warren.cli` additionally runs the actual
    work on a worker thread with a 512MB stack, extending the
    comfortably-working range far past ordinary program sizes (tested
    to 50,000 elements). Library callers embedding `warren` directly on
    the default thread remain bounded by (a) alone (tested clean to
    tens of thousands of elements on this box's default 8MB stack) —
    documented in README as a known limit, not hidden.

## What's still a known, disclosed limitation (not "fixed" because it
isn't actually broken relative to how real Prolog behaves)

- **No occurs-check.** `X = f(X)` succeeds and produces a genuinely
  cyclic term, exactly like SWI-Prolog's default (`unify_with_occurs_check/2`
  exists as a separate, opt-in predicate in real systems; Warren doesn't
  implement that opt-in variant, but the default behavior matches).
  Printing or copying such a term would not terminate — same as any
  Prolog with occurs-check off.
- **`*->`'s soft-cut semantics are simplified**, documented already in
  `compiler.py`: Warren's `*->` behaves like a plain disjunction between
  `(Cond,Then)` and `Else` rather than true ISO soft-cut (which
  additionally suppresses `Else` the instant `Cond` succeeds even once,
  regardless of what `Then` does afterward). `*->` isn't in Warren's
  required or stretch feature list; noted for honesty, not treated as a
  bug to fix today.
- **No last-call optimization** (see finding #2's fix): every body goal
  is a genuine `call` with a pushed continuation, so deep recursion
  costs environment-stack space, not Python call-stack depth — it
  works (tested to 20,000 recursive calls), it's just not
  constant-space the way a textbook WAM's tail calls are.

## Fresh run-through after fixes

All 75 tests green, including: the full differential battery
(WAM vs. golden-model, 65 cases across cut, if-then-else, disjunction,
negation, `catch/throw`, `assert/retract`, DCG, and both example
puzzles), the CLI end-to-end (clean errors for a missing file, a syntax
error, an undefined predicate; a 20,000-element list run through the
big-stack worker thread), and every regression test written directly
against a finding above. Re-ran the original repro for each of the ten
findings by hand after the fixes; none reproduce.
