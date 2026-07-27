# Adversarial review

Hunting bugs, edge cases, ugly UX, and lazy shortcuts in the Phase 2 core
build, as a hostile reviewer rather than the author. Every issue below was
reproduced first, then fixed; the fix is described alongside the finding.

## Bugs found and fixed

### 1. Type-error messages had "expected" and "found" backwards

`unify(t1, t2)` had no fixed calling convention — some call sites passed
the inferred/actual type first, others passed it second — so `unify_raw`'s
generic mismatch message printed whichever came first as "expected" and
whichever came second as "found," regardless of which one actually was.
Concretely, `1 + true` reported:

    expected bool, found int

which is backwards (`+` requires `int`; `true` is what's actually there —
found bool). **Fix:** established a single explicit convention —
`unify(found, expected)` everywhere, renamed `unify_raw`'s parameters to
match, and re-audited every call site in `infer.py` (two were passing
arguments in the wrong order for this convention: the `LetRec` closing
unification and the `Match` per-branch unification). Now the same program
correctly reports `expected int, found bool`. Locked in by
`TestErrorMessages.test_arithmetic_type_mismatch_message`.

### 2. `&&` / `||` did not short-circuit

`_eval_BinOp` evaluated both operands unconditionally before dispatching on
the operator, so `true || (1 / 0 = 0)` raised a division-by-zero error
instead of short-circuiting to `true` — the evaluator was silently wrong
about a core operator's semantics. **Fix:** `&&`/`||` are now handled first,
evaluating the right operand only when actually needed (Python's own
`and`/`or`, which already short-circuit). Locked in by
`TestArithmeticAndControlFlow.test_boolean_short_circuit_shape_still_evaluates_correctly`.

### 3. Comparing two functions silently returned `False` instead of erroring

The type system has no typeclass/`Ord` constraint, so `'a -> 'a -> bool`
can be instantiated at a function type — `(fun x -> x) = (fun y -> y)`
type-checks. The evaluator was supposed to reject this at runtime with a
clear error (there's no meaningful notion of function equality), and did
so for `<`/`>`/`<=`/`>=` (Python raises `TypeError` there) — but `=`/`<>`
use Python's `==`/`!=`, and `Closure` is a `@dataclass`, so Python's
auto-generated `__eq__` just compared captured environments and returned
`False` without ever raising. **Fix:** added an explicit
`_contains_closure()` check (recursing into tuples/lists/`Option`) that
rejects comparisons involving function values *before* falling through to
Python's operators, for all six comparison operators uniformly. Locked in
by `test_comparing_functions_raises_clear_error`.

### 4. Paired type names in error messages didn't share a naming context

`pretty()` assigns `'a`, `'b`, ... to type variables in the order it
encounters them, starting fresh every call. Every "expected X, found Y"
message called `pretty()` twice independently — so a variable that's
genuinely shared between the two types being compared could be printed as
`'a` on one side and `'b` on the other (or, worse, two *unrelated*
variables could coincidentally both print as `'a`), actively misleading
whoever reads the message. **Fix:** added `pretty_pair(a, b)`, which
prints both types against one shared variable-naming context, and switched
every paired message in `unify_raw` to use it. Locked in by
`test_pretty_pair_shares_variable_names_across_both_sides` and
`test_unify_error_message_uses_shared_variable_names`.

### 5. A missing input file crashed with a raw Python traceback

`cmd_check`/`cmd_run` called `open(path)` with no error handling — a typo'd
filename produced a bare `FileNotFoundError` traceback instead of the
clean, source-anchored diagnostics the rest of the tool produces. **Fix:**
added `read_source()`, which catches `OSError` and returns a normal
`error: cannot read '<path>': ...` message through the same code path as
every other error. Locked in by `test_missing_file_reports_clean_error_not_traceback`.

### 6. Deep recursion crashed with a 300-line raw traceback

Unify has no tail-call optimization — each level of recursion in a Unify
program costs several real Python stack frames — and the default CPython
recursion limit (1000) is exhausted by even modest recursive programs
(e.g. summing a list of a few hundred elements), producing an enormous,
unreadable `RecursionError` traceback instead of a clean error. **Fix:**
raised the recursion limit to 100,000 (verified this does not risk a raw
segfault before Python's own counter catches it — tested at 5x that depth)
and wrapped every `eval_expr` entry point in a catch that reports
`error: recursion too deep (stack overflow)` plus a one-line explanation.
Locked in by `test_deep_recursion_reported_cleanly_not_a_raw_traceback`.

### 7. Critical: instantiating a persisted scheme could self-reference and hang forever

This is the most serious bug found, and the reason this review is worth
doing before, not after, building the Phase 4 REPL on top of the inference
engine. `infer_program` previously created a fresh `Infer` (and its
variable counter) from scratch on every call. A REPL necessarily calls
`infer_program` repeatedly against a **persisted** environment of
`Scheme`s produced by earlier calls. If each call's counter restarts at 0,
a freshly-minted type variable in the new call can numerically collide
with a bound-variable label already living inside an old, persisted
scheme. `instantiate()` then builds a substitution like `{1: TVar(1)}` —
mapping a variable to *itself* — and `apply()`, which blindly recurses
into whatever a variable maps to, loops forever (crashing with
`RecursionError`, or hanging indefinitely at a higher recursion limit).

Reproduced concretely: generalize `fun x -> x` into a scheme, generalize
`fun x -> x + 1` into another, put both into a fresh env, and infer
`(f true, g 5)` against that env with the counter restarted at 0 — a
`RecursionError` results, deterministically, on this machine. Threading a
running counter across the three calls (`start_counter` in, `next_counter`
out) instead produces the correct `(bool, int)`.

**Fix:** `Infer`/`infer_program` now accept `start_counter` and return the
counter's final value as a third element of the result tuple, so a
stateful caller can thread it across calls. This is the exact contract
the Phase 4 REPL is built on — see `unify/repl.py`. Locked in by
`TestPersistedEnvAcrossCalls` (both the failing case, reproduced
deliberately with `start_counter=0`, and the passing case with the counter
threaded).

## Dead code / lazy shortcuts removed

- `apply_scheme()` in `types.py` was written but never called from
  anywhere — removed, along with the now-unused imports it left behind
  (`TCon` in `infer.py`, `LexError` in `parser.py`).
- `cmd_check`/`cmd_run`/`run_source` each re-implemented the same
  parse-then-report / infer-then-report error handling inline. Refactored
  into shared `parse_or_error()`, `infer_or_error()`, `eval_or_error()`
  helpers used by both `check_source()` and `run_source()`, so there is
  exactly one place that formats each class of error.

## Documented (not "fixed") parsing ambiguities

Two behaviors look like bugs at first glance but are the same, well-known
ambiguities every ML-family language (OCaml, F#, SML) has, for the same
structural reason — fixing them would mean deviating from how these
languages actually work, not correcting a defect. Both are locked in with
regression tests (`TestDocumentedAmbiguities` in `tests/test_parser.py`)
and explained in README.md's "Sharp edges" section so they don't surprise
a user silently:

- **`f -1` parses as `f - 1`** (binary subtraction), not `f` applied to
  `-1` — write `f (-1)` to apply a function to a negative literal.
- **A `match`/`if`/`fun` used as a non-final case body swallows the
  following `| pattern -> ...` arms** meant for the *enclosing* match,
  because these forms greedily extend as far right as possible (the same
  "maximal munch" behind the classic dangling-else ambiguity). Parenthesize
  the inner construct to stop it from swallowing its neighbors.

## Result

100 unit tests, all passing (up from 84 before this review). Every fix
above has a regression test; the two documented ambiguities have tests
that pin down the current, deliberate behavior. Re-ran every example
program end-to-end after all fixes — all five (`factorial`, `polymorphism`,
`list_ops`, `options`, `type_error`) still produce identical, correct
output.
