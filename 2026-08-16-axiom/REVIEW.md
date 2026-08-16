# Adversarial Review — Axiom

Phase 3: attacking the Phase 2 build as a hostile reviewer — hunting for
bugs, broken edge cases, ugly UX, and lazy shortcuts, then fixing every one
found. This was a genuine stress-testing pass (finite-difference/Simpson's-
rule oracles against random points, differential testing against an
independent brute-force determinant, live Playwright exploitation of the
browser playground), not a token scan. 12 real issues were found and fixed,
one of them a working, exploitable security bug.

## Issues found and fixed

1. **Confusing polynomial term ordering.** `Add`'s canonical form sorted
   terms purely by string representation, so `expand((x+1)^3)` printed as
   `x^3 + 3*x + 3*x^2 + 1` — mathematically fine, but nobody reads
   polynomials in that order. **Fix:** added a degree-aware sort key so terms
   print in the conventional highest-degree-first order
   (`x^3 + 3*x^2 + 3*x + 1`).

2. **Printer bug: spurious parens around negative Add terms.** `x - 2` printed
   as `x + (-2)` because the pretty-printer's Num-parenthesization rule
   triggered on any elevated precedence context, not just where parens are
   actually needed. **Fix:** scoped the rule to the one case where a negative
   number genuinely needs parens (as a `Pow` base — `(-2)^2 ≠ -2^2` under our
   own grammar).

3. **Real parser/printer round-trip bug.** `sqrt(x)` printed as `x^1/2`
   (no parens around the fractional exponent). Re-parsing that string gives
   `(x^1)/2`, **not** `x^(1/2)`, since the grammar's exponent slot binds
   tighter than `/`. Any pipeline that prints then re-parses an expression
   with a fractional power was silently wrong. **Fix:** parenthesize a
   fractional-Num exponent specifically (`x^(1/2)`), verified round-trip
   for radicals, negative integer exponents (`x^-2`, correctly *not*
   parenthesized — it round-trips fine as-is), and nested towers (`x^y^2`).

4. **`Num`/`Symbol`/etc.'s dataclass-generated `__repr__` silently shadowed
   the intended pretty-printing `__repr__`** inherited from `Expr`, so e.g.
   `print(solve(...))` on a list of roots showed `[Num(value=Fraction(3, 1))]`
   instead of `[3]`. **Fix:** `repr=False` on all six node dataclasses.

5. **`pi`/`e` couldn't be numerically evaluated.** The parser recognizes
   `pi`/`e` specially, but `evalf()` had no fallback for them and raised
   "free symbol has no numeric binding" — breaking anything downstream that
   evaluates an expression containing `pi` (the plotter, `axiom eval`).
   **Fix:** `evalf()` now falls back to `math.pi`/`math.e` when the symbol
   isn't explicitly bound (an explicit binding, if given, still wins).

6. **Uncaught `RecursionError` on deeply nested input.** `parse("(" * 500 +
   "x" + ")" * 500)` crashed with a raw Python traceback, not a clean parse
   error — the same class of bug this repo's own Kiln/Ember builds flagged
   before. **Fix:** an explicit, documented nesting-depth cap (100 levels,
   comfortably under `sys.getrecursionlimit()` for this grammar's
   frames-per-level) raising a clean `ParseError` instead.

7. **`Matrix.det()` fell short of the plan's own architecture.** PLAN.md
   promised "cofactor expansion + Bareiss for larger," but only cofactor
   expansion (O(n!)) was shipped — impractical past ~8×8. **Fix:**
   implemented the promised Bareiss fraction-free elimination (O(n³), exact,
   no floating point) as the fast path whenever every entry is a plain
   number, with cofactor expansion kept as the fallback for symbolic
   entries. Verified against an independent brute-force cofactor oracle
   across 50+ random trials, including matrices that force a mid-elimination
   pivot swap (zero on the diagonal) — 0 mismatches. 12×12 dropped from
   "would take minutes" to 2.6 ms.

8. **Integration coverage gap on textbook u-substitution.** `x/(x²+1)`,
   `2x·exp(x²)`, and `sin(x)·cos(x)` — three of the first substitution
   examples in any calculus course — all reported "out of scope," because
   the integrator only recognized *linear* inner arguments. **Fix:** added a
   general substitution rule that recognizes `f(g(x))·g'(x)` for any `g`, not
   just linear ones, via exact polynomial-ratio checking with a numeric-probe
   fallback for the transcendental case (`sin(x)`/`cos(x)` aren't
   polynomials in `x`, but their ratio is still a plain constant) — and
   confirmed the fallback can't produce a false positive: verified against
   genuinely non-constant-ratio cases (`x·exp(x³)`) staying correctly
   unsupported, and every accepted result checked against a finite-difference
   derivative.

9. **`axiom eval --bind x=abc` crashed with a raw traceback** (`float()` on
   non-numeric input, unguarded). **Fix:** validated with a clean
   `AxiomError`; also added a global catch-all in `main()` so no CLI
   invocation can ever leak a raw Python traceback, matching the standard
   this repo holds every CLI tool to.

10. **Float noise in `axiom eval`.** `sqrt(-1)` printed as
    `6.123233995736766e-17+1j` instead of `1j`, because Python's native
    complex `**` operator isn't exact for irrational powers of negative
    numbers. **Fix:** epsilon-snap near-zero real/imaginary components at the
    CLI print boundary only (the underlying `evalf()` numerics are untouched
    — this is presentation-layer, not a kernel change).

11. **`sin(pi*x)` couldn't auto-infer its variable.** `pi` parses as an
    ordinary `Symbol`, so `axiom diff "sin(pi*x)"` saw two free symbols
    (`pi`, `x`) and demanded `--var` be spelled out for what should be an
    obvious case. **Fix:** the "guess the variable" heuristic (CLI and HTML
    report) now excludes `pi`/`e` from the candidate pool unless they're
    the *only* symbol present.

12. **Security: reflected XSS in the live playground.** `/api/analyze`'s
    error path concatenated the raw, attacker/user-controlled expression
    text directly into `innerHTML` with no escaping — a `ParseError`'s
    message repeats the offending input verbatim in its caret diagnostic.
    Submitting `<img src=x onerror=alert(1)>` as the expression executed
    arbitrary JavaScript in the browser. **Reproduced live** with a headless
    Playwright session (confirmed the `alert()` fired), **fixed** by
    building the error display with `document.createElement`/`textContent`
    instead of string-concatenated `innerHTML`, and **re-verified the exploit
    no longer fires** with the same live reproduction.

## One more, found during Phase 5 (writing the test suite)

A randomized "factor a polynomial, then re-expand it and demand the exact
original coefficients back" test (the same kind of oracle this build
promised throughout PLAN.md) failed on `-x^2 - 5*x + 3`: re-expanding its
factored form gave `-x^2 - 5*x + 37/4 - 25/4` — numerically equal to `3`,
but printed as **two separate, never-combined constant terms**, which is
supposed to be structurally impossible in a kernel that folds every
constant into one running accumulator.

**Root cause, traced to `mul()` itself:** when `mul()` combines repeated
factors of the same base by summing their exponents (`x^a · x^b -> x^(a+b)`),
a base can itself be a plain number (e.g. the `37` in an unresolved radical
`37^(1/2)`). If the *summed* exponent happens to fully resolve
`power(base, exponent)` back down to a plain `Num` — exactly what happens
when a factored quadratic's two conjugate radical terms multiply back
together, `37^(1/2) · 37^(1/2) -> 37^1 -> 37` — that resulting `Num` was
appended to the factor list as if it were an ordinary symbolic factor,
instead of being folded into the running numeric coefficient. The result:
a `Mul` silently holding two never-multiplied `Num`s side by side. Every
downstream `add()` call then saw that malformed `Mul` as a distinct
"term" rather than a foldable constant, so it never merged with a sibling
plain-`Num` term — the exact **structural invariant** this whole kernel is
built on ("every expression is always fully folded") was quietly false in
this one path.

**Fixed** by folding any `Num`-resolving factor into `coeff` at the point
`mul()` reconstructs its factor list, with the failure mode and the exact
factored-quadratic trigger documented in the code itself so it can't
regress silently. Re-verified against 200 freshly-seeded random polynomials
(degree 1–5, `factor()` → `expand()` → exact coefficient match) with zero
mismatches, plus the full existing test suite still green.

This is the same class of finding several of this repo's past builds have
flagged as their worst bug (Coil's GC-untracking hazard, Loom's autograd
reference cycle): invisible until a specific structural combination is
exercised, caught only by testing the *invariant* (re-expand and demand
exact equality) rather than eyeballing a few happy-path outputs.

## What a fresh run-through now looks like

- `python3 -m axiom.cli demo` — all sections print correctly, every inline
  assertion passes, exit code 0.
- Deep/malformed input (`x+`, `foo(x)`, 500-deep parens, `--bind x=abc`,
  `<script>`-shaped playground input) — every path returns a clean,
  human-readable error. Zero raw tracebacks found in this pass.
- Finite-difference/Simpson's-rule spot checks across ~20 expressions and
  the Bareiss-vs-cofactor determinant cross-check — zero mismatches.
- The playground XSS is closed and re-verified with a live browser
  reproduction, not just code inspection.

## Scope decisions carried forward (not bugs — disclosed limitations)

- `factor()` only fully factors via the rational root theorem plus one
  final real/complex quadratic. A quartic like `x^4 + 4` (factorable over
  ℚ into two irreducible quadratics via the Sophie Germain identity) is
  correctly left unfactored rather than guessed at — `solve()` still finds
  its exact complex roots numerically (Durand-Kerner), so the *root-finding*
  feature isn't limited by this, only the *factored-form-display* feature.
  Full factoring over ℚ needs a Berlekamp/Zassenhaus-style algorithm, out of
  scope for this build.
- `Matrix.det()`'s O(n!) cofactor path is still what symbolic-entry
  matrices use (Bareiss needs exact division by a running numeric pivot,
  which isn't generally meaningful for arbitrary expressions) — fine at the
  matrix sizes this build's demo/tests use, documented as a ceiling.
