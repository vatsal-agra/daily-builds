# Adversarial review

Method: fuzz the core invariants directly rather than only hand-picked
examples -- differentiation cross-checked against numerical finite
differences, integration cross-checked by differentiating the result back
and comparing to the original integrand at sample points, `factor()`
cross-checked by re-expanding and comparing to the original, `solve()`
cross-checked by substituting every returned root back into the original
equation and expanding -- plus targeted attacks on error handling (malformed
input, non-polynomial input, unsolvable/non-integrable expressions,
division-by-zero-shaped input) through both the library API and the CLI.

## Issues found and fixed

1. **CRITICAL -- `mul()`'s own output could violate its own flatness
   invariant, silently hiding atoms from later simplification.**
   `add()`'s like-term combining built its result term via a raw
   `Mul((Num(coeff), rest))` where `rest` could itself already be a
   (separately, correctly flat) `Mul` -- producing a `Mul` whose direct
   child is another `Mul`, a structure `mul()`'s own flatten step (at the
   time, one level deep) never expected from *its own* prior output. Caught
   by the solve-root-verification fuzzer: `-4*x^2-2*x-5=0`'s root
   `-1/4*i*sqrt(19) - 1/4`, substituted back and squared, printed as
   `-1/4*(i*sqrt(19))^2 - 19/4` instead of collapsing to the exact zero it
   mathematically is -- `i` and `sqrt(19)` were trapped together inside a
   nested `Mul` that a later multiplication's same-base combining never
   looked inside. Root cause reproduced directly with
   `mul(add(t, t), add(t, t))` for `t = -1/4*i*sqrt(19)`. Fixed two ways:
   `add()` now reconstructs its terms through `mul()` instead of a raw
   `Mul(...)`, and `mul()`'s own flatten step is now fully recursive
   (flattens a `Mul` nested at any depth), so this class of bug can't
   recur even from a future raw-construction site.
2. **Missing exact-power rules that made the bug above possible in the
   first place.** `pow_()` had no rule for `i**n`, `sqrt(u)**n`, or
   `(f1*f2*...)**n` for integer `n` -- each left a bare `Pow` node
   sitting around uncombined (`sqrt(13)**2` staying `sqrt(13)^2` instead of
   `13`; `(2*x)**3` staying `(2*x)^3` instead of `8*x^3`). Added all three
   as exact rules in `pow_()` (the `i**n` and `(f1*f2*...)**n` rules are
   always exact for integer `n` -- no branch-cut ambiguity, since an
   integer power is just repeated multiplication regardless of sign),
   which also let the now-redundant special-cased imaginary-unit handling
   inside `mul()` be deleted in favor of one canonical place (`pow_()`)
   that folds `i**n`.
3. **`1/0` (and any `0**negative`) silently returned an inert `0^(-1)`
   symbolic expression instead of raising.** An `if/elif` chain in `pow_()`
   meant the `base == 0` branch's failure to match `exp > 0` fell all the
   way through the whole numeric-power-folding block instead of being
   treated as an error. Fixed to raise `ZeroDivisionError` for `0` raised
   to a negative or otherwise non-positive-numeric power (`0**0` still
   returns `1` by the usual convention, matched *before* this check).
4. **`factor()` crashed on the zero polynomial whenever no variable
   survived cancellation** (e.g. `factor(0*x)`, `factor(x - x)`): it called
   `univariate_var()` -- which requires *exactly one* free variable --
   before ever checking whether the expression was just zero, so the
   entirely-reasonable "please factor 0" request raised `NotPolynomial`
   instead of returning `0`. Fixed by simplifying and checking for the
   zero polynomial first.
5. **`mul()` was inconsistently eager: `2*(x+1)` auto-distributed to
   `2*x+2` but `(x+1)*(y+1)` silently stayed factored**, purely because the
   old rule only distributed when *exactly one* `Add` factor was present.
   A hostile read of the code turned up no principled reason for the
   asymmetry -- it was an accident of the original implementation, not a
   design choice, and it made "simplify" behave unpredictably depending on
   incidental structure. Generalized `mul()` to fully distribute whenever
   *any* `Add` factor remains, so multiplication is now exactly as eager as
   addition; `factor()`'s intentionally-factored output is unaffected
   because it already builds its result through the raw `Add`/`Mul`
   constructors, deliberately bypassing `mul()`, rather than depending on
   `mul()` to hold something back.
6. **Rendering ugliness**: a standalone negative product printed as
   `-1*sqrt(2)` / `-1*i` instead of `-sqrt(2)` / `-i` (the "-" shorthand
   only applied inside `Add`'s own term-joining, not to a `Mul` printed on
   its own -- visible directly on `solve`'s output for irrational/complex
   roots); `Add.to_str`/`to_latex` also didn't apply the shorthand to a
   *first* term, so `x - i` rendered as `-1*i + x`. Both fixed. `sqrt(8)`
   stayed `sqrt(8)` instead of the customary `2*sqrt(2)` (no largest-square-
   factor extraction), which made exact quadratic-formula roots uglier than
   necessary (`1/2*sqrt(8)` instead of `sqrt(2)`) -- added square-free-factor
   extraction to `sqrt`'s folding. `factor()` on a polynomial with a
   fractional rational root printed the technically-correct but unusual
   `(x + 1/2)*2` instead of the conventional `(2*x + 1)`; `factor()` now
   clears each root's denominator into its own linear factor and folds
   every numeric scale contribution (content, cleared root denominators,
   the quadratic-remainder leading coefficient) into a *single* overall
   constant instead of scattering separate `Num` factors through the
   product.
7. **Error-path sweep** (parser, `solve`, `integrate`, `factor`, the CLI,
   and the REPL) confirmed clean, typed exceptions and non-zero exit codes
   with no tracebacks for: empty input, malformed syntax (`2+*3`,
   `sin(x` unbalanced, trailing tokens), multivariate input to `factor`,
   a non-polynomial equation to `solve` (`sin(x)=0`), an integrand outside
   the supported rule set (`exp(x^2)`), an inconsistent or underdetermined
   linear system, and a CLI command missing a required `--var`/`--at`
   binding it can't infer. No fixes needed here -- called out because a
   hostile review that *only* looks for things to fix and never confirms
   the negative case is worth less.

## What's verified now (all at zero mismatches after the fixes above)

- Differentiation vs. numerical finite differences, 7 mixed
  polynomial/trig/exp/log/power expressions x 5 random points each.
- Integration self-consistency (differentiate the antiderivative back,
  compare to the original integrand numerically), 15 cases spanning every
  rule (power, 1/x, affine sin/cos/exp/ln/tan/sqrt, exponential-base,
  tabular integration by parts) x 4 random points each.
- `factor()` vs. `expand()` round-trip over 400 random integer-coefficient
  polynomials of degree 1-5 (rational, irrational-real, and complex roots
  all included).
- `solve()`'s roots substituted back into the original equation and
  expanded, over 400 random quadratics.

## Known, deliberate scope boundaries (not bugs)

- `simplify()`/`equal()` do not expand `Pow(Add, n)` (e.g. `(x+1)^2` stays
  `(x+1)^2`) -- only the explicit `expand()` does binomial expansion. This
  matches how `mul()`/`add()` treat an *already fully-formed* Add specially
  but a **power** of one is a separate, potentially much larger, operation
  better left to an explicit call. `equal()`'s docstring says as much, and
  verifying a `solve()`/`factor()` identity that involves squaring a
  substituted root needs `expand()` for exactly this reason (the "verified
  now" section above does this).
- Integration remains a scoped rule table (see PLAN.md), not a decision
  procedure; `exp(x**2)`, `sin(x)*ln(x)`, etc. correctly raise
  `CannotIntegrate` rather than guessing.
- A higher-degree polynomial with no more rational roots falls back to
  numeric (Durand-Kerner) complex roots, clearly reported as `numeric_roots`
  and printed with a `~=` and a `(numeric)` tag, never mixed silently into
  the exact `roots` list.
