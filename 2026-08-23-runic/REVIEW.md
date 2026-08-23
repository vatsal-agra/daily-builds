# Runic — Adversarial Review (Phase 3)

Attacking the Phase 2 build as a hostile reviewer: hunting for bugs, broken
edge cases, ugly UX, and lazy shortcuts. Every issue below was found, then
fixed, then re-verified — this file is the record of both.

## Bugs found and fixed

### 1. Control-flow frame leak in `if` handling (real correctness bug)

**How it was found:** not by inspection — by the dual-oracle verifier
itself. `fib.rn`, `factorial.rn`, `gcd.rn`, and `is_prime.rn` all passed
cleanly (single level of loop nesting each), but `bubble_sort.rn` and
`sieve.rn` — the first programs with an `if` nested two `while` levels
deep — disagreed with Node: our interpreter produced a subtly wrong
answer (a partially-sorted array) while Node's real engine, loading the
exact same bytes, produced the correct one.

**Root cause:** `interpreter.py`'s `if` opcode handling always pushed a
control-flow frame, then jumped straight to the position *after* the
matching `end` when the condition was false and there was no `else`
branch — bypassing the `end` opcode that would normally pop that frame.
The pushed frame leaked permanently onto the control stack, silently
corrupting the relative-depth arithmetic for every `br`/`br_if` that ran
afterward in the same function call. On a single-`if`, single-loop
program the leak never mattered (the loop's own exit check ran before the
`if`, so the corrupted depth was never used again before the function
returned). It only surfaced with a *second* level of loop nesting after
the `if`, where a now-off-by-one relative depth pointed at the wrong
frame and silently skipped loop iterations.

**Fix:** only push the frame when a branch is actually going to be
traversed (then-branch, or else-branch); when skipping the entire
construct (false condition, no else), jump straight past with no frame
bookkeeping needed. Symmetrically, the `else` marker (reached by falling
through after a taken then-branch) now explicitly pops the frame before
jumping past the else-branch, instead of leaving it dangling.

**Why this matters for the project's premise:** this is exactly the class
of bug a toy interpreter checked only against its own compiler's output
would never surface — the compiler's codegen and the interpreter's
execution were self-consistent with each other, just both wrong relative
to the actual WASM spec. Checking against Node's independent, spec-
faithful engine is what turned an invisible bug into a two-line repro.

### 2. Non-canonical LEB128 encoding for large literals (real encoder bug)

**How it was found:** deliberately probing the boundary the type checker
allows — Runic accepts literals in the full `[-2^31, 2^32-1]` range so
that both `-1` and its unsigned spelling `4294967295` are legal and mean
the same bit pattern. `4294967295` compiled and even *ran* successfully
under our own interpreter (producing `-1`, since `sleb128_decode`
normalizes on the way back out) — but Node's `WebAssembly.instantiate`
outright **rejected the module**: `extra bits in varint`.

**Root cause:** `codegen.py` passed the literal's raw Python int value
straight to `i32.const`, and `encoder.py`'s signed-LEB128 encoder treated
`4294967295` as the (large, positive) number it is, not as the 32-bit bit
pattern for `-1` — producing a longer, non-canonical byte sequence that
happens to *decode* back to the right value by our own lenient decoder,
but that a real, spec-strict validator refuses to load at all.

**Fix:** normalize every `i32.const` immediate to canonical signed
32-bit range (`i32_wrap`) before encoding — once at the actual source in
`codegen.py`, and defensively again in `encoder.py`'s instruction encoder
in case any other code path ever emits a raw immediate.

**Severity note:** this one is worse than bug #1 in one respect — bug #1
produced a *wrong answer*; this one produced *bytes a real engine refuses
to even load*, which is the sharpest possible version of "the encoder and
the decoder silently agreed on the wrong thing" that the dual-oracle
design exists to catch, since our own decoder is lenient enough to have
hidden it completely.

### 3. Raw Python tracebacks for ordinary CLI mistakes (UX)

`cli.py run` crashed with a full Python traceback (no clean error, no
recognizable exit behavior) for every one of: a non-integer argument, a
wrong argument count, an unknown function name, and a missing source
file. Only compile-time errors (parse/semantic) were already handled
cleanly. Fixed by introducing a single `CliError` wrapper caught once at
the top of `main()`, and having every command raise it with a specific,
actionable message instead of letting the underlying exception surface
raw. Re-verified all four cases now print a one-line `error: ...` message
and exit 1.

### 4. Unbounded recursion crashed with a raw `RecursionError` (UX +
   spec-fidelity)

Since WASM `call` is implemented as an actual Python function call,
deep Runic-level recursion (e.g. summing 1..5000 recursively) eventually
hit Python's own recursion limit and surfaced as a raw
`maximum recursion depth exceeded` traceback. A real WASM engine has the
same *kind* of bound — a finite native call stack — and represents
exhausting it as a **trap**, not a host-language crash. Fixed by catching
`RecursionError` at the interpreter's outer call boundary and converting
it into a `WasmTrap("call stack exhausted")`, which the CLI now reports
as a clean `trap: call stack exhausted` like any other trap.

## Things checked and found correct (not bugs, but worth recording)

- **Short-circuit evaluation of `&&`/`||`** actually skips the
  right-hand side at runtime, not just semantically — verified with a
  side-effecting call (an array write) on the RHS: the array is left
  untouched when the LHS short-circuits, and written when it doesn't.
- **Memory is page-granular (64KiB), as required by the spec.** Reading
  past the end of a small declared array but still inside the allocated
  page is *legal* (returns zero) in both our interpreter and Node;
  reading past the whole page traps in both. Initially looked like it
  might be a bug (`buf[10000]` on a 4-element array doesn't trap!) until
  cross-checked against Node, which does the exact same thing — this is
  correct WASM memory semantics, not a leniency bug in either
  implementation.
- **Signed division/remainder** (truncating toward zero, `INT_MIN / -1`
  overflow trap, `INT_MIN % -1 == 0` without a trap) all match the spec
  and match Node exactly, including with a negative divisor on both
  sides.

## Known, documented (not fixed) limitations

- **Call-stack depth is bounded by Python's recursion limit** (now
  reported as a clean trap rather than a crash — see fix #4 above — but
  still a real, much-lower-than-typical-real-engines ceiling on how deep
  Runic-level recursion can go). Scope decision: raising
  `sys.setrecursionlimit` would move the ceiling but not remove it, and
  real engines vary in their own stack limits too; a from-scratch
  tree-walking-via-Python-calls interpreter inherently has this shape of
  constraint.
- **No `break`/`continue`/`goto`** in the Runic language — a deliberate
  scope decision from PLAN.md, not a bug: it keeps every `br`/`br_if`
  target's relative depth statically known at codegen time.

## Fresh run-through after fixes

`python3 verify.py` — 11 programs (9 original + 2 new regression cases
for bugs #1 and #2's failure modes), every call and every trap agreeing
byte-for-byte between the from-scratch interpreter and Node's native
WebAssembly engine. `cli.py run/trace` re-checked against all four CLI
misuse cases from finding #3 — clean one-line errors, no tracebacks.
