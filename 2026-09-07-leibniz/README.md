# Leibniz

A computer algebra system built entirely from scratch in pure Python:
parse ordinary math notation, canonicalize/simplify it exactly, differentiate
it, integrate it, solve equations exactly, and factor/expand polynomials —
all in exact rational arithmetic (`fractions.Fraction`), never floating
point except where a result is genuinely numeric.

See [PLAN.md](PLAN.md) for the full design, feature list, and why this is a
new domain for this repo.

**Status: Phase 3 (adversarial review) complete.** See [REVIEW.md](REVIEW.md)
for what was found (including one critical canonicalization bug) and fixed,
plus the fuzz-based verification now in place. The four required features
are implemented and working end-to-end:

1. Expression parser + canonical simplifier
2. Symbolic differentiation (sum/product/quotient/power/chain/generalized
   `f^g`, sin/cos/tan/exp/ln/sqrt)
3. Exact equation solving (linear, quadratic with exact symbolic
   discriminant, general polynomial via rational-root extraction, plus
   linear systems via exact Gaussian elimination)
4. Polynomial expand/factor (full distribution; GCD extraction + rational
   root theorem factoring)

Stretch features (symbolic integration, HTML step visualizer) are also
already working, ahead of the adversarial-review and polish passes still to
come.

## Quick tour

```
./leibniz_cli simplify "2*x + 3*x - 1"          # 5*x - 1
./leibniz_cli expand "(x+1)*(x-2)"              # x^2 - x - 2
./leibniz_cli factor "x^2 - 5*x + 6"            # (x - 2)*(x - 3)
./leibniz_cli diff "x^2*sin(x)" --var x         # cos(x)*x^2 + 2*x*sin(x)
./leibniz_cli integrate "x^2*exp(x)" --var x    # exp(x)*x^2 - 2*x*exp(x) + 2*exp(x) + C
./leibniz_cli solve "x^2 - 5*x + 6 = 0" --var x # x = 3 / x = 2
./leibniz_cli solve-system "2*x+y=5" "x-y=1" --vars x,y
./leibniz_cli eval "sin(x)^2 + cos(x)^2" --at x=1.234
./leibniz_cli repl
./leibniz_cli diff "x^3" --var x --viz out.html  # step-by-step HTML visualizer
```

Run `python3 -m unittest discover tests` from this directory for the test
suite (more tests to come in Phase 5).
