# Leibniz

A computer algebra system built entirely from scratch in pure Python:
parse ordinary math notation, canonicalize/simplify it exactly, differentiate
it, integrate it, solve equations exactly, factor/expand polynomials, and
simplify rational functions — all in exact rational arithmetic
(`fractions.Fraction`), never floating point except where a result is
genuinely numeric and clearly labeled as such.

See [PLAN.md](PLAN.md) for the full design, [REVIEW.md](REVIEW.md) for the
adversarial-review findings (including one critical canonicalization bug)
and how they were fixed and verified.

## What it is

Leibniz never evaluates an expression until asked to — `diff(x**2*sin(x), x)`
returns a new expression tree, not a number. That's the thing that actually
distinguishes a *computer algebra system* from a numeric library or an
autodiff engine (this repo already has both: Cotangent's autodiff
differentiates a computation *at a point*; it never sees a bare variable
`x`, let alone expands, factors, or solves anything). Under the hood:

- an expression tree (`Num`/`Symbol`/`Add`/`Mul`/`Pow`/`Func`, plus `i`/`pi`/`e`)
  with smart constructors that keep everything in one canonical, fully
  simplified form as it's built — flattened, constants folded exactly,
  like terms and like powers combined, `i**n`/`sqrt(u)**n`/`(f*g)**n` all
  folded correctly for integer `n`;
- a hand-written tokenizer + recursive-descent parser for real math
  notation (`2*x^3 - sin(x)/(x+1)`, implicit multiplication, `^` or `**`);
- symbolic differentiation with the full rule set, including a single
  logarithmic-differentiation formula that correctly reduces to the plain
  power rule, the exponential rule, or the general `f(x)^g(x)` case
  depending on what actually depends on the variable;
- exact equation solving: linear, quadratic (the discriminant's square root
  stays exactly symbolic — `sqrt(2)`, or an exact multiple of `i` for a
  negative discriminant — never a float), general polynomials via
  rational-root extraction down to an exactly-solved quadratic remainder
  (with a clearly-labeled numeric fallback for whatever's left), and linear
  systems via exact Gaussian-Jordan elimination;
- polynomial expansion and factoring (GCD extraction + the rational root
  theorem, with exact-radical linear factors for an irrational quadratic
  remainder);
- rule-based symbolic integration (linearity, the power rule, the standard
  affine-argument sin/cos/exp/ln/tan/sqrt table, an exponential-base rule,
  and tabular integration by parts for polynomial × {exp, sin, cos}) that
  raises a clear `CannotIntegrate` rather than guessing when nothing
  matches;
- rational-function simplification (`ratsimp`): combine a sum of fractions
  in one variable over a common denominator and cancel their GCD —
  `(x^2-1)/(x-1)` → `x + 1`;
- an interactive, self-contained HTML step-by-step visualizer (no server,
  no external assets) that replays a captured derivation as a real
  expression-tree diagram alongside a scrubbable step list.

## How to run it

```bash
cd 2026-09-07-leibniz

# the CLI
./leibniz_cli simplify "2*x + 3*x - 1"          # 5*x - 1
./leibniz_cli expand "(x+1)*(x-2)"              # x^2 - x - 2
./leibniz_cli factor "x^2 - 5*x + 6"            # (x - 2)*(x - 3)
./leibniz_cli diff "x^2*sin(x)" --var x         # cos(x)*x^2 + 2*x*sin(x)
./leibniz_cli integrate "x^2*exp(x)" --var x    # exp(x)*x^2 - 2*x*exp(x) + 2*exp(x) + C
./leibniz_cli solve "x^2 - 5*x + 6 = 0" --var x # x = 3 / x = 2
./leibniz_cli solve-system "2*x+y=5" "x-y=1" --vars x,y
./leibniz_cli ratsimp "(x^2-1)/(x-1)"           # x + 1
./leibniz_cli eval "sin(x)^2 + cos(x)^2" --at x=1.234
./leibniz_cli repl                              # interactive REPL
./leibniz_cli diff "x^3" --var x --viz out.html # step-by-step HTML visualizer

# the test suite
python3 -m unittest discover tests

# everything at once (unit tests + every CLI path + a real headless-
# Chromium check of the generated visualizer)
./demo.sh
```

No dependencies to install — pure Python 3 standard library throughout.
`demo.sh`'s visualizer check uses the pre-installed Playwright/Chromium if
available and skips gracefully otherwise.

## Full feature list

**Required (all four work end-to-end, no stubs):**

1. Expression parser + canonical simplifier
2. Symbolic differentiation (sum/product/quotient/power/chain/generalized
   `f^g`, sin/cos/tan/exp/ln/sqrt), verified against numerical finite
   differences
3. Exact equation solving (linear, quadratic with an exact symbolic
   discriminant, general polynomial via rational-root extraction, linear
   systems via exact Gaussian elimination), verified by substituting every
   root back into the original equation
4. Polynomial expand/factor (full distribution; GCD extraction + rational
   root theorem factoring, exact radical factors for an irrational
   quadratic remainder), verified by re-expanding and comparing to the
   original

**Stretch (both shipped):**

5. Rule-based symbolic integration, verified by differentiating the result
   back and comparing to the original integrand numerically
6. Interactive, dependency-free HTML step-by-step visualizer
   (expression-tree diagram + scrubbable step list), screenshot- and
   headless-Chromium-verified

**Bonus, beyond the plan:**

7. Rational-function simplification (`ratsimp`) — combine over a common
   denominator and cancel the GCD

**Plus:** a full CLI (`simplify`/`expand`/`factor`/`diff`/`integrate`/
`solve`/`solve-system`/`ratsimp`/`eval`/`repl`) and a REPL, all with clean
typed errors (never a raw Python traceback) for malformed input,
non-polynomial input to `factor`/`solve`, unsupported integrals, and
division-by-zero-shaped input.

## Why this, today

This repo has built an enormous amount of from-scratch mathematics —
autodiff, numeric ODE/circuit simulation, quantum state vectors, fluid
PDEs, SAT solving, type inference, regex automata, a spreadsheet formula
engine — but never a **symbolic algebra system**: software that manipulates
*unevaluated* expressions containing variables as first-class objects and
proves things about them, rather than computing with numbers or vectors.
That's a genuinely different shape of problem (canonical forms, exact
rational arithmetic, structural equality) from anything else in this
repo's history, and it comes with unusually strong closed-form ground
truth for verification — a derivative checked against a numerical
finite difference, a root checked by substitution, a factorization checked
by re-expanding — which made adversarial review (Phase 3) turn up a real,
subtle, and satisfying bug: `mul()`, the arithmetic core every other module
is built on, could produce output that violated its own internal
flatness invariant, hiding an `i` and a `sqrt(19)` from each other so a
mathematically-exact-zero substituted root printed as a nonzero leftover
power. See REVIEW.md for the full story.

## Where a human could take this next

- A real Risch-style decision procedure for integration (or at least a
  broader rule table: `1/(1+x^2)` → `arctan`, trig-substitution patterns,
  more general integration-by-parts pattern matching beyond
  polynomial × {exp, sin, cos}).
- Multivariate calculus: partial derivatives, gradients, multiple
  integrals, the multivariate chain rule.
- A general Risch-adjacent or Sturm's-theorem-based real-root isolator for
  higher-degree polynomials with no rational roots, rather than the current
  Durand-Kerner numeric fallback.
- Symbolic matrices (determinant, inverse, eigenvalues) — natural next
  domain, and the exact-`Fraction` arithmetic here is already the right
  foundation for it.
- Trig-identity simplification (`sin(x)^2+cos(x)^2 -> 1`, sum-to-product,
  etc.) as a `simplify()` extension beyond the special-value folding
  already in place.
- A LaTeX-in/LaTeX-out mode, or wiring the existing `to_latex()` into the
  HTML visualizer for properly typeset (not monospace-string) expressions.
