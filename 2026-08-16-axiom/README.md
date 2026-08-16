# Axiom — a Computer Algebra System from scratch

A from-scratch **computer algebra system (CAS)**: it parses real math
notation, manipulates it *symbolically* — differentiates, integrates,
solves equations, factors and expands polynomials, does exact matrix
algebra — and produces exact answers, not floating-point approximations.
`d/dx(x² sin(x))` returns `2x·sin(x) + x²·cos(x)`, exactly, in closed form.

No floats live in the kernel: every number is a Python `fractions.Fraction`,
so `0.1 + 0.2` is exactly `3/10`, not `0.30000000000000004`. `~3,150` lines
of pure Python 3 stdlib, zero runtime dependencies.

## Why this, today

This repo has built a numeric autodiff engine (Cotangent) and a type
inference engine (Unify) before, but never something that reasons about
the *structure* of a mathematical expression and returns another exact
expression as the answer. A CAS also offers an unusually strong,
self-generating correctness oracle that this build leans on hard: transform
an expression, then **evaluate both the original and the transformed form
at random points and demand exact or near-exact agreement** — differentiate
`f`, check the result against a finite-difference estimate of `f`'s slope;
factor a polynomial, re-expand it, and demand the *exact* original
coefficients back; solve an equation, substitute the root back in, and
demand the residual is zero. That "verify against ground truth, not vibes"
discipline is exactly what caught this build's worst bug (see
[REVIEW.md](REVIEW.md)) — a randomized "factor → re-expand → compare exact
coefficients" test found a real kernel invariant violation that every
hand-picked example had missed.

## Try it

```bash
python3 -m axiom.cli demo                 # full walkthrough, every feature
python3 -m axiom.cli simplify "sqrt(8) + sqrt(2)"     # -> 3*2^(1/2)
python3 -m axiom.cli diff "x^2*sin(x)" --steps        # -> with rule-by-rule trace
python3 -m axiom.cli solve "x^2 - 5x + 6"             # -> 2, 3
python3 -m axiom.cli solve "x^2 + 1"                  # -> 1j, -1j
python3 -m axiom.cli factor "x^3 - 8"                 # -> (x-2)*(x^2+2x+4)
python3 -m axiom.cli integrate "x*exp(x)"             # -> x*exp(x) - exp(x) + C
python3 -m axiom.cli eval "0.1 + 0.2"                 # -> 0.3, exactly
python3 -m axiom.cli latex "x^2/(x-1)"                # -> \frac{x^2}{x-1}
python3 -m axiom.cli repl                             # interactive shell
python3 -m axiom.cli viz "x^2*sin(x)" --out r.html    # static HTML report
python3 -m axiom.cli serve                            # live browser playground
./demo.sh                                             # everything, verified
```

No install step beyond a working `python3` — the whole engine is stdlib.

## Feature list

**Required (4):**

1. **Parser + canonical simplification.** Real infix math syntax (`+ - * /
   ^`, implicit multiplication `"2x"`/`"3(x+1)"`, unary minus, nested
   function calls) parsed into an expression tree that's *always* in
   canonical form: like terms collected, constants folded exactly via
   `Fraction`, exponent laws applied (`x^a·x^b -> x^(a+b)`), and even
   partial radical extraction (`sqrt(8) -> 2·sqrt(2)`, `(-8)^(1/3) -> -2`).
2. **Symbolic differentiation.** The full elementary rule set (sum, product,
   quotient via power rule, chain, and the generalized `f(x)^g(x)`
   logarithmic-differentiation rule) composes automatically through
   arbitrarily nested expressions and all 13 built-in functions
   (`sin/cos/tan/exp/log/sqrt/abs/asin/acos/atan/sinh/cosh/tanh`). Exposes
   an ordered, human-readable rule-application trace (`--steps`).
3. **Equation solving.** Linear equations exactly; quadratics via the
   quadratic formula (real, exact-radical, or complex roots); higher-degree
   polynomials via the rational root theorem followed by Durand-Kerner
   simultaneous iteration for whatever's left — every root verified by
   substitution residual, not just "the iteration converged."
4. **Polynomial expand / factor / GCD.** Full distribution (`expand`),
   factoring via rational-root peeling plus an exact/radical quadratic
   formula for the final degree-2 remainder, and polynomial GCD via the
   Euclidean algorithm — every factorization checked by re-expanding to the
   *exact* original coefficients.

**Stretch (3 shipped — 2 planned + 1 bonus):**

5. **Symbolic integration.** Power/sum rules, a function table composed
   with linear-argument substitution, the two `1/(1+x²)`→`atan` /
   `1/√(1-x²)`→`asin` patterns, tabular integration by parts for
   polynomial×{exp,sin,cos,sinh,cosh}, and a general u-substitution rule
   (`f(g(x))·g'(x)` for *any* `g`, not just linear — covers textbook cases
   like `x/(x²+1)` and `sin(x)·cos(x)`). Genuinely out-of-scope integrals
   (e.g. `exp(x²)`) raise a clear error instead of guessing.
6. **Interactive HTML visualizer** — real LaTeX-subset typesetting (a small
   renderer this build wrote itself, no MathJax/KaTeX CDN), an SVG plot of
   `f(x)` and `f'(x)` from genuine numeric sampling, and a step-by-step
   derivative trace with play/prev/next controls. Ships two ways: a static
   single-file report (`axiom viz`) and a **live, server-backed playground**
   (`axiom serve`) where a real `http.server` backend runs the actual Python
   kernel against arbitrary typed-in expressions — the browser holds zero
   symbolic-math logic, the same pattern this repo's Gambit/Formulate/
   Faraday builds established.
7. **Symbolic matrices** — `+`, `*`, transpose, determinant (Bareiss
   fraction-free elimination for numeric matrices — exact, O(n³), not the
   O(n!) naive approach; cofactor expansion for symbolic entries), the
   adjugate/inverse, and linear-system solving via Cramer's rule.

## Verification

- **154 unit tests** across parser/kernel/calculus/solve/polynomial/matrix/
  CLI, plus a `sympy` differential-testing module (dev-only dependency,
  never imported by shipped code — skips gracefully if unavailable).
- Differentiation checked against central finite differences; integration
  checked against Simpson's-rule definite integrals *and* by
  differentiating the result back; factoring checked by re-expanding to
  exact original coefficients; every equation root checked by substitution
  residual; the Bareiss determinant cross-checked against an independent
  brute-force cofactor oracle across 200+ random trials.
- `demo.sh` — 19 end-to-end checks: the full unit suite, a real CLI
  walkthrough of every feature, clean-error-on-malformed-input checks (no
  raw tracebacks), and a live headless-Chromium smoke test of the browser
  playground that includes a permanent regression check for the XSS bug
  found and fixed during review (see below).
- See [REVIEW.md](REVIEW.md) for the adversarial-review writeup: 12 issues
  found and fixed in Phase 3 (including a working, reproduced-and-fixed XSS
  vulnerability in the live playground), plus one more serious kernel bug
  caught by Phase 5's randomized testing.

## Honest scope limits (disclosed, not hidden)

- `factor()` fully factors via the rational root theorem plus one final
  real/complex quadratic formula. A polynomial like `x^4 + 4` — factorable
  over ℚ into two irreducible quadratics via the Sophie Germain identity —
  is correctly left unfactored rather than guessed at (full factoring over
  ℚ needs a Berlekamp/Zassenhaus-style algorithm). `solve()` isn't limited
  by this: it still finds `x^4+4`'s exact complex roots numerically.
- Integration covers the elementary techniques listed above; a genuinely
  non-elementary or unrecognized integral raises a clear error rather than
  returning something wrong.
- `Matrix.det()`'s exact-numeric fast path is Bareiss (O(n³)); symbolic-entry
  matrices still use O(n!) cofactor expansion (Bareiss needs exact division
  by a running *numeric* pivot, which isn't generally meaningful for
  arbitrary symbolic entries) — fine at the sizes this build's tests/demo
  use, documented as a ceiling rather than silently slow.

## Architecture

```
axiom/expr.py        the AST + canonicalizing smart constructors (the only
                      place auto-simplification logic lives)
axiom/parser.py       tokenizer + recursive-descent/precedence-climbing parser
axiom/simplify.py     extra rewrite passes: sin²+cos²=1, rational-function reduction
axiom/calculus.py     differentiation + integration
axiom/polynomial.py   expand / factor / GCD / polynomial long division
axiom/solve.py        linear / quadratic / Durand-Kerner equation solving
axiom/matrix.py       exact/symbolic matrices, Bareiss determinant
axiom/latex.py        expression -> LaTeX
axiom/report.py       the HTML visualizer + live playground server
axiom/cli.py          the `axiom` command-line tool
```

See [PLAN.md](PLAN.md) for the full design rationale and
[REVIEW.md](REVIEW.md) for the adversarial review.

## Where a human could take this next

- **Full rational-function simplification**: differentiation currently
  produces mathematically correct but not maximally-combined results for
  quotient rule outputs (e.g. `-2x²/(x²+1)² + (x²+1)⁻¹` instead of
  `(1-x²)/(x²+1)²`) — a "combine over a common denominator" pass on `Add`
  (beyond the single-fraction cancellation `simplify()` already does) would
  close that.
- **Full polynomial factoring over ℚ** (Berlekamp/Zassenhaus or similar)
  would remove the one disclosed `factor()` limitation above.
- **Exact symbolic complex numbers** (an `i` unit with its own arithmetic
  rules) instead of falling back to Python `complex` for non-real roots —
  would let `solve()` return exact complex expressions like `2 + 3*i`
  instead of numeric approximations for irrational complex roots.
- **A trig-identity engine** beyond the one Pythagorean pattern
  `simplify()` knows — angle-sum/difference, double-angle, product-to-sum.
- **Series expansion** (Taylor/Maclaurin) would fit naturally next to
  `differentiate()`/`integrate()` using the same kernel.
