# Axiom — a Computer Algebra System from scratch

## Concept

A **computer algebra system (CAS)**: software that manipulates mathematical
expressions *symbolically* rather than numerically — `d/dx(x^2 sin(x))`
returns `2x·sin(x) + x²·cos(x)`, not a floating-point slope at one point.
This is the engine underneath Mathematica, Maple, SymPy, and the "solve for
x" button on Wolfram|Alpha: an expression tree, an exact-arithmetic kernel,
and a set of algebraic rewrite rules that are provably correct, not just
plausible-looking.

This repo has built two adjacent-but-distinct things before: **Cotangent**
(2026-06-16), a *numeric* reverse-mode autodiff engine over a scalar `Value`
DAG that computes gradients by running the computation forward, and **Unify**
(2026-07-27), a Hindley-Milner *type* inference engine that reasons about the
shape of programs without running them. Axiom is neither: it reasons about
the *structure* of a mathematical expression itself and produces another
expression as the answer, exactly, in closed form, over the rationals (and
their algebraic extensions) — no floating point in the kernel, and nothing
here has touched polynomial factoring, symbolic integration, or exact
equation solving before.

## Why it's interesting

A CAS is a genuinely different kind of "from-scratch" than a solver or an
interpreter: correctness isn't "did it terminate with a plausible answer,"
it's "is this rewritten expression provably the same function as the input
for every value of its variables." That gives an unusually strong,
free ground-truth oracle that this build leans on hard: for any expression
`e`, transform `e` to `e'` and then **evaluate both at a pile of random
rational/real points and demand exact or near-exact agreement**. Differentiate
`f` to get `f'`, then check `f'` against a central-finite-difference estimate
of `f`'s slope. Factor a polynomial into `(x-2)(x+3)`, then re-expand and
demand the *exact* original coefficients back, not "close." Solve `ax²+bx+c=0`
for `x`, then substitute the root back into the original equation and demand
the residual is exactly (or numerically, for irrational/complex roots) zero.
This is the same "verify against ground truth, not vibes" ethos this repo's
crypto (NIST vectors), VCS (real git), and search-engine (BM25 hand
derivation) builds have used — just with a self-generating oracle (random
points + finite differences) instead of an external reference implementation,
because a CAS *is* the ground truth once its core rules are proven right.

## Architecture

```
axiom/
  expr.py       Expression AST: Symbol, Rational (exact, via Fraction),
                 Add, Mul, Pow, Function (sin/cos/tan/exp/log/sqrt/abs).
                 Structural equality + hashing so expressions are usable
                 as dict keys (needed for term collection).
  parser.py      Tokenizer + Pratt/recursive-descent parser: infix +-*/^,
                 unary minus, implicit multiplication ("2x", "3(x+1)"),
                 function calls, nested parens, positioned syntax errors.
  simplify.py    Canonical-form rewrite engine: flatten nested Add/Mul,
                 constant-fold exact rationals, combine like terms
                 (collect coefficients of structurally-equal factors),
                 apply exponent laws (x^a·x^b -> x^(a+b), (x^a)^b -> x^(a*b)),
                 drop identities (x+0, x*1, x*0, x^0, x^1), canonical
                 term ordering so equal expressions compare structurally
                 equal after simplification.
  calculus.py    Symbolic differentiation: sum/product/quotient/power/chain
                 rules, derivatives of sin/cos/tan/exp/log/sqrt, composed
                 automatically through the chain rule for nested functions.
                 Symbolic integration: power rule, sum rule, table lookup
                 for exp/sin/cos/1/x, u-substitution recognition for
                 f(g(x))·g'(x) patterns, integration by parts for
                 polynomial × {exp, sin, cos}.
  polynomial.py  Dense coefficient-vector view of a single-variable
                 polynomial expression: expand() (fully distribute Mul over
                 Add, incl. Pow with positive integer exponent), collect
                 into coefficient form, polynomial GCD via the Euclidean
                 algorithm, factor() (extract GCD monomial, difference of
                 squares, sum/difference of cubes, quadratic formula
                 factoring, rational root theorem + synthetic division for
                 degree >= 3).
  solve.py       Equation solver: isolate-the-variable for linear
                 equations, the quadratic formula (real + complex roots,
                 exact when the discriminant is a perfect square, otherwise
                 exact-radical form), and Durand-Kerner simultaneous
                 iteration for real/complex roots of higher-degree
                 polynomials, refined by the rational-root theorem for
                 exact rational roots when they exist.
  matrix.py      Symbolic/exact matrices over Axiom expressions: +, *,
                 determinant (cofactor expansion + Bareiss for larger),
                 inverse (adjugate/Cramer for small, Gauss-Jordan with
                 exact Fraction pivoting for larger), linear system solve.
  latex.py       Expression -> LaTeX renderer (proper fraction/power/
                 function typesetting, operator precedence-aware
                 parenthesization) used by both the CLI and the HTML report.
  cli.py         `axiom` command-line tool: simplify/diff/integrate/solve/
                 factor/expand/matrix/repl/viz/demo subcommands.
  report.py      Generates the self-contained interactive HTML visualizer.
```

No third-party dependencies in shipped code (Python 3 stdlib only —
`fractions.Fraction` for exact rational arithmetic is the only "magic").
`sympy` is used **only** as a development-time cross-check oracle inside the
test suite (never imported by any shipped `axiom/` module), the same
external-oracle pattern this repo has used with real `git`/`openssl`/`gcc`
before.

## Feature list

**Required (4):**
1. **Parser + expression AST + canonical simplification** — parse real
   infix math syntax into a symbolic tree, simplify it to a canonical form
   (like-term collection, constant folding, exponent laws), exactly, via
   `Fraction`-based rational arithmetic (no float drift).
2. **Symbolic differentiation** — full rule set (sum, product, quotient,
   power, chain) composing automatically through arbitrarily nested
   expressions and built-in functions (`sin/cos/tan/exp/log/sqrt`),
   verified against numerical finite differences.
3. **Equation solving** — linear equations exactly; quadratics via the
   quadratic formula (real and complex roots, exact-radical when
   irrational); higher-degree polynomials via Durand-Kerner + rational-root
   refinement, every root verified by substitution residual.
4. **Polynomial expand/factor + GCD** — full distribution (`expand`),
   factoring (common factor, difference of squares/cubes, quadratic
   trinomials, rational-root synthetic division for higher degree), and
   polynomial GCD via the Euclidean algorithm — every factorization
   verified by re-expanding to the exact original coefficients.

**Stretch (2, +1 if time allows):**
5. **Symbolic integration** — power/sum rules, a function table, u-substitution
   pattern recognition, and integration by parts for polynomial×{exp,sin,cos},
   every antiderivative verified by differentiating it back (rule 2's engine)
   and by numerical definite-integral cross-check (Simpson's rule).
6. **Interactive HTML visualizer** — type an expression, see it typeset in
   real LaTeX (via `latex.py`, rendered client-side with a small self-contained
   LaTeX-subset-to-SVG/HTML renderer — no MathJax/KaTeX CDN), an animated
   function+derivative plot (SVG, computed from real numeric evaluation of
   the symbolic tree), and a step-by-step derivation trace (simplification
   and differentiation both expose an ordered list of the rewrite rules they
   applied, not just a final answer).
7. **(if time) Symbolic matrices** — determinant/inverse/linear-system-solve
   over exact `Fraction` or symbolic entries, verified against Cramer's rule
   and `A·A⁻¹ = I`.

## Verification strategy

- Random-point numeric evaluation: after any simplification, `simplified(x)
  == original(x)` for many random rational `x` (and multi-variable points
  for multi-symbol expressions).
- Differentiation vs. central finite differences, several step sizes,
  several points, across every built-in function and nesting depth.
- Factoring vs. re-expansion: `factor(p)` expanded back must equal `p`'s
  *exact* coefficient vector, not an approximation.
- Equation roots vs. substitution residual (exact for rational roots, `< 1e-9`
  for numeric/complex roots).
- Integration vs. its own derivative (round-trips through rule 2) and vs.
  Simpson's-rule definite-integral estimates.
- `sympy` (dev-only, test-suite-only) as a second, independent oracle
  wherever it's convenient, to cross-check the from-scratch engine's
  behavior against a real production CAS.
