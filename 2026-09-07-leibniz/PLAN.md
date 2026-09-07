# Leibniz — a Computer Algebra System from scratch

## Concept

A symbolic mathematics engine: parse ordinary math notation into an
expression tree, canonicalize/simplify it, differentiate it, integrate it,
solve equations exactly, and factor/expand polynomials — all in exact
rational arithmetic (`fractions.Fraction`), never floating point, except
where a result is genuinely irrational/transcendental and there is no exact
closed form (flagged honestly as numeric, never silently rounded and passed
off as exact).

## Why this is interesting / why it's a new domain for this repo

This repo has built an enormous amount of from-scratch mathematics and
computation over 64 prior entries — autodiff (Cotangent), numeric ODE/circuit
simulation (Faraday), quantum state vectors (QSim), fluid PDEs (Flux), SAT
solving (Conflux/Backjump), type inference (Unify), regex automata
(RegexLab) — but never a **symbolic algebra system**: software that
manipulates *unevaluated* mathematical expressions containing variables as
first-class objects, and proves things about them (this derivative is
exactly this expression; this factorization, re-expanded, is exactly the
original; this root, substituted back, exactly zeroes the equation).
Cotangent's autodiff is the closest relative and is instructive by contrast:
it differentiates a numeric computation *at a point* (a `Value` DAG holding
floats), never sees a variable `x`, and never expands, factors, or solves
anything. Leibniz never evaluates until asked to — `diff(x**2 * sin(x), x)`
returns a new expression tree, not a number — which is the actual
distinguishing feature of a CAS (and of Mathematica/SymPy/Maple in the real
world) versus a numeric or autodiff library.

Named for Gottfried Leibniz, co-inventor of calculus notation (the product
rule and the `d/dx` notation this project literally implements), following
this repo's convention of naming from-scratch math/science builds after the
historical figures behind the underlying idea (Shannon, Faraday, Cotangent).

## Architecture

```
leibniz/
  expr.py        Expression tree: Num (exact Fraction), Symbol, Add, Mul,
                 Pow, Func (sin/cos/tan/exp/ln/sqrt), plus I (imaginary
                 unit) and Pi/E as special symbolic constants. Operator
                 overloads (+ - * / **) so expressions build like normal
                 Python arithmetic. Structural __eq__/__hash__ so canonical
                 forms can be compared and used as dict keys.
  parser.py      Tokenizer + Pratt/recursive-descent parser for standard
                 math notation ("2*x^3 - sin(x)/(x+1)"), producing an
                 expr.py tree. Implicit multiplication (2x, x(x+1)) and
                 both ^ and ** for power.
  simplify.py    Canonicalization: flatten nested Add/Mul, fold constants
                 exactly over Fraction, collect like terms, combine powers
                 of identical bases, canonical sort order so structurally
                 equal expressions always print and compare identically.
                 Every other module normalizes its output through this.
  diff.py        Symbolic differentiation: sum/product/quotient/power/chain
                 rules, the generalized f(x)^g(x) case via logarithmic
                 differentiation, and derivatives of sin/cos/tan/exp/ln/sqrt.
  polynomial.py  expand() (full distribution), collecting a univariate
                 polynomial's coefficients as a Fraction list, polynomial
                 long division, a Euclidean poly-GCD (for cancelling common
                 factors in rational expressions), and factor() (GCD
                 extraction + rational-root-theorem based factoring).
  solve.py       solve(equation, var): linear (degree 1), quadratic (exact
                 quadratic formula — the discriminant's sqrt is kept exactly
                 symbolic via Func('sqrt', ...), imaginary roots via I when
                 the discriminant is negative, never a float), general
                 polynomial via repeated rational-root extraction down to a
                 quadratic remainder, and linear systems via exact Gaussian
                 elimination over Fraction.
  integrate.py   Rule-based symbolic integration: linearity, the power
                 rule (incl. the x**-1 -> ln|x| special case), the standard
                 sin/cos/exp/1/x table with linear-argument substitution
                 (∫sin(ax+b)dx), and tabular integration by parts for
                 polynomial × {exp, sin, cos} products. Explicitly raises
                 `CannotIntegrate` rather than guessing when no rule
                 applies — an honest scope boundary, not a silent wrong
                 answer.
  render.py      Expression -> human-readable string and -> LaTeX, plus a
                 `Steps` recorder that every module above appends
                 human-readable derivation steps to, consumed by the CLI's
                 `--steps` flag and by the HTML visualizer.
  cli.py         `leibniz` CLI: simplify/diff/integrate/solve/expand/factor/
                 eval subcommands, a REPL, and `viz` to emit the HTML
                 visualizer for a captured derivation.
viz/
  generate_viz.py  Builds a self-contained single-file HTML visualizer
                   (expression-tree diagram + step-by-step derivation
                   replay) from a JSON step trace, no server needed.
tests/           unittest suite: parser round-trips, simplifier identities,
                 diff checked against numerical finite differences (the
                 same cross-check technique Cotangent/Sprout used for their
                 from-scratch gradients, applied here to a *symbolic*
                 derivative instead of a numeric one), integration checked
                 by differentiating the antiderivative back and comparing
                 numerically at sample points, solve() checked by
                 substituting roots back into the original equation,
                 factor() checked by re-expanding and comparing to the
                 original expansion.
```

## Feature list

**Required (core, must work end-to-end with no stubs):**

1. **Expression parser + canonical simplifier** — parse real math text into
   a tree, and simplify it into one canonical exact form (flatten, fold
   constants over `Fraction`, combine like terms and like powers).
2. **Symbolic differentiation** — full rule set (sum, product, quotient,
   power, chain, generalized `f^g`, and sin/cos/tan/exp/ln/sqrt),
   cross-checked against numerical finite differences.
3. **Exact equation solving** — linear, quadratic (exact symbolic
   discriminant, real or imaginary roots), and general polynomial via
   rational-root extraction; solutions verified by substitution back into
   the original equation.
4. **Polynomial expand/factor** — full distribution, and factoring via GCD
   extraction plus the rational root theorem; every factorization verified
   by re-expanding it and comparing to the original.

**Stretch:**

5. **Symbolic integration** — rule-based antiderivatives including
   integration by parts for polynomial × exp/sin/cos, verified by
   differentiating the result and checking it matches the original
   integrand numerically at sample points.
6. **Interactive HTML step-by-step visualizer** — replays a captured
   derivation (simplification/diff/integration/solve steps) as an
   expression-tree diagram with a scrubbable step list, no server or
   external assets.

## Bonus, beyond the planned feature list

7. **Rational-function simplification** (`ratsimp`) — combine a sum of
   fractions in one variable over a common denominator via `poly_mul`/
   `poly_add`, then cancel their GCD via the existing `poly_gcd`
   (implemented in Phase 2 for factoring but originally unused elsewhere).
   `(x^2-1)/(x-1)` -> `x+1`; `1/x + 1/(x+1)` -> `(2*x+1)/(x^2+x)`. Added in
   Phase 4 polish once the two committed stretch features (integration, the
   HTML visualizer) were both already done in Phase 2.

## Honest scope boundaries (decided up front, not discovered late)

- Integration is rule-based, not a full decision procedure (no Risch
  algorithm). Anything outside the supported pattern set raises
  `CannotIntegrate` with a clear message rather than returning a wrong or
  partial answer.
- General polynomial solving beyond quadratic only finds *rational* roots
  exactly; an irreducible higher-degree remainder is reported as "no
  further exact rational roots," not silently dropped or approximated as
  if exact.
- Multivariate calculus (partial derivatives of many variables, multiple
  integrals) is out of scope — everything above is single-variable, which
  is already a complete, honestly-bounded product.
