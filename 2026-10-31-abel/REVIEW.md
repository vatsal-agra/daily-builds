# Abel — Adversarial Review (Phase 3)

Method: I attacked the Phase-2 build as a hostile reviewer would — a ~190-line battery of edge,
degenerate, malformed and "does it lie?" inputs (`testdata/review_attack.txt`), a stress file
(`testdata/review_stress.txt`: huge exponents, 3000-deep parentheses, high-degree factoring, big
integrals), plus reading the code for shortcuts. Every item below was reproduced first, then fixed,
then the battery was re-run (`abel -f testdata/review_attack.txt` → 0 `internal error`, every
listed input now behaves as described in the "After" column).

## Bugs and wrong answers

| # | Attack | Before | After |
|---|--------|--------|-------|
| 1 | `sin(x)^2+cos(x)^2` | stayed `cos(x)^2 + sin(x)^2` | `1`; also `1-sin(x)^2 → cos(x)^2` (Pythagorean rule in `Add`) |
| 2 | `e^(i*pi)` | unevaluated | `-1` (exact `exp(i·c·π)` via the 30°/45° table) |
| 3 | `1/(1+sqrt(2))` | `1/(sqrt(2) + 1)` — two equal-valued forms of a surd existed | `sqrt(2) - 1` (conjugate rationalisation for two-term denominators whose squares are rational; also `1/(1+i)`) |
| 4 | `1.5e2` | parsed as `3/2 * e2` — silently wrong | `150` (lower-case exponent in the lexer) |
| 5 | `solve(a*x^2+b*x+c=0, x)` | printed `≈ 0` next to symbolic roots (a lie: evaluation failed and defaulted to 0) | approximation only shown when the root has no free symbols |
| 6 | `solve(y=2, x)` | `no solutions` (false: it's a condition on `y`) | error: *the equation does not involve x* |
| 7 | `integrate(x^2, x, a, b)` | claimed "✓ cross-checked against numeric quadrature" although the limits were symbolic and nothing was checked | message printed only when the check actually ran (`DefiniteIntegral` now returns `checked`) |
| 8 | `integrate(1/sqrt(x), x, 0, 1)` | "diverges or needs a principal value" (wrong: it converges to 2) | honest: *improper integral … limits are not implemented*; `ln(0) is undefined` leaks fixed the same way |
| 9 | `foo(x)` | silently `foo*x`; `diff(f(x), x)` returned `f` | parse error: unknown function (multi-letter name directly followed by `(`) |
| 10 | `taylor(1/x, x, 0, 3)` | bare `division by zero` | explains the series is singular at the expansion point |
| 11 | `taylor(ln(x), x, 1, 4)` | `-(x - 1)^4/4 + … + x - 1` — nested sum flattened so the k=1 term looked like a stray `x - 1` | expanded polynomial for rational centres |
| 12 | `solve(x^12-1=0, x)`, `x^4+1` | decimals for roots expressible in radicals | exact roots through `p(x)=q(x^k)` substitution with exact roots of unity; `-0` normalised in output |
| 13 | any internal panic | would kill the REPL | `Session.Eval` recovers and reports `internal error` (never triggered by the battery) |
| 14 | 3000-deep parentheses | relied on Go stack growth | parser depth cap (300) with a positioned error |
| 15 | `eigen([[1,2],[3,4]])` | irrational eigenvalues printed without saying vectors are missing | explicit note |

## Missing capability that a reviewer would call a lazy gap

| # | Attack | Before | After |
|---|--------|--------|-------|
| 16 | `factor(x^30-1)` | **10 s then "too large"** — Kronecker's method is exponential in degree | Replaced for degree ≥ 4 by Zassenhaus (mod-p factoring: distinct-degree + Cantor–Zassenhaus, quadratic Hensel lifting, subset recombination). `x^30-1`, `x^45-1` factor in ≈ 0.05 s. Kronecker is kept as a test oracle. |
| 17 | `integrate(sin(x)^10)`, `x^8*e^x` | failed (recursion depth 7) | depth 30 + budget; plus a direct tabular rule for `P(x)·{exp,sin,cos}(ax+b)` |
| 18 | `integrate(sin(2x)*cos(3x))` | no closed form | product-to-sum rewrite |
| 19 | `integrate(1/(1+e^x))` | no closed form (u=e^x found, but `e^(-x)` did not match structurally) | `substLike` recognises `e^(q·w)` and `x^m` as powers of the substitution variable |
| 20 | `integrate(sqrt(1-x^2))`, `1/sqrt(1-x^2)` | no closed form | completing-the-square rule for `Q^(±1/2)`, Q quadratic (asin / ln forms) |
| 21 | `integrate(abs(x))` | no closed form; `abs` could not even be evaluated numerically | `x·|x|/2`; evaluator knows `abs` |
| 22 | `integrate((3x+2)/(x^2+2x+5))` | `ln((x+1)^2+4)` — correct but not the original denominator | `ln(x^2 + 2x + 5)` |

## Accepted limitations (documented, fail loudly, never wrong)

* Rational integrands whose denominator has an irreducible factor of degree > 2 over Q
  (`1/(x^4+1)`) need algebraic-number partial fractions. The error says exactly that.
* Improper integrals (endpoint singularities) — the answer is refused rather than guessed; no limits engine.
* `solve` is exact through quadratics (+ `q(x^k)` patterns); other irreducible polynomials of degree ≥ 3 get numeric roots, labelled as such.
* Multivariate factoring (`x^2-y^2`) is not implemented; error says so.
* `1/(x^2+x+1)^2`-style antiderivatives are correct and certified but not pretty-printed over a single denominator.
* `(-8)^(1/3)` stays unevaluated (principal branch is complex; the real root is only used numerically).
* `sqrt(x^2)` is not rewritten to `|x|` (we do not track assumptions).

## Verification of the review itself

Every integral printed by the battery carries Abel's own certificate (derivative re-check at up to 60
random points, or exact symbolic cancellation). Nothing in the "After" column is a hardcoded output.

## Addendum (Phase 5): bugs the property tests found in my "fixed" build

Writing the randomised tests exposed two more genuine defects that the hand-written battery had missed.
Both are fixed and covered by `TestPrintParseRoundTrip` / `TestSimplifierTable`.

| # | Found by | Defect | Fix |
|---|----------|--------|-----|
| 23 | print→parse round trip on 3000 random expressions | The canonical form was *association-dependent*: `Mul` distributed a numeric coefficient over a lone sum only when the product had exactly two factors, so `4225*(x-24)/(…)` parsed to a different tree than the one that printed it. | `Mul` never distributes. `Add` distributes a bare `c*(a+b)` term (so `x - (x+1)` still cancels), and a presentational `Tidy` pass cleans up results. |
| 24 | same test | Numeric content under a power was not normalised: `(2x+2)^-1` and `(1/2)(x+1)^-1` were different trees for the same value. | `Pow` pulls the rational content (and, for integer powers, the sign) out of a sum; a first version looped forever on sign-flipping — caught by the same test, termination rule added. |
| 25 | finite-difference test | (test bug, not engine) huge-magnitude samples gave spurious mismatches | tests skip samples whose function value / slope is outside a sane range |
