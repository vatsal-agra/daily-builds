# Abel — PLAN

## Concept
Abel is a from-scratch **computer algebra system (CAS)** in Go, standard library only
(`math/big` for exact arithmetic). Type `integrate((x^2+1)/(x^3+x), x)` and get a closed form,
type `factor(x^4+4)` and get `(x^2 - 2x + 2)(x^2 + 2x + 2)`. Every answer is exact
(arbitrary-precision rationals, surds, `pi`, `e`, `i`) — never floating point, unless you ask.

Nothing in this repo's ledger is symbolic mathematics (Kepler *discovers* equations numerically,
Milner/Horn/Tarski are logic, Dantzig is LP). A CAS is the classic "everything-must-be-right"
program: its answers can be **certified**, so Abel checks itself — every integral is
differentiated back and compared numerically at random points; every factorisation is multiplied back.

## Why it's interesting
* Canonical forms: two equal expressions must normalise to the *same tree* — the core CAS problem.
* Symbolic integration is a search over heuristics (linearity, tables, u-substitution,
  integration by parts, trig-power reduction, partial fractions) — and failing honestly matters.
* Exact polynomial factorisation over Q (Yun square-free + rational roots + Kronecker) is real algebra.

## Architecture
```
cas/expr.go       immutable Expr tree: Num(*big.Rat) Sym Add Mul Pow Fn Mat; canonical constructors
cas/simplify.go   like-term collection, power merging, surd extraction, function identities, Expand
cas/parse.go      lexer + precedence-climbing parser (implicit multiplication, equations, matrices)
cas/print.go      pretty printer (fractions, signs, e^x, sqrt)
cas/eval.go       complex128 numeric evaluator (the certifier's oracle)
cas/diff.go       differentiation + Taylor series
cas/poly.go       univariate Q[x]: arith, gcd, square-free, Kronecker factorisation, roots, apart
cas/solve.go      equation solving (exact to quadratics, numeric Aberth beyond)
cas/integrate.go  integration engine + definite integrals + certifier
cas/matrix.go     exact rational matrices: det, inverse, rref, solve, charpoly, eigenvalues
cas/interp.go     command dispatch for the REPL / CLI
cmd/abel          REPL, one-shot (-e) and script (-f) modes
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Parser + canonical exact simplifier/expander (rationals, surds, i, constants, identities) | **required** |
| 2 | Symbolic differentiation (chain/product/quotient/general power, partial & higher order) | **required** |
| 3 | Polynomial toolkit: expand, gcd, square-free, factor over Q, solve (exact ≤ quadratic, numeric beyond), partial fractions | **required** |
| 4 | Symbolic integration (linearity, table, u-sub, by parts, trig powers, rational via partial fractions) + definite integrals + self-certification | **required** |
| 5 | Taylor/Maclaurin series | stretch |
| 6 | Exact rational matrices: det, inverse, rref, solve, charpoly, eigenvalues | stretch |
| 7 | REPL with variables, `ans`, script mode, numeric `N()` | secondary (core UX) |
| 8 | Self-certifier: numeric re-check of derivatives/integrals/factorisations | secondary |

## Definition of done
All required features end-to-end, REVIEW.md of real attacks with fixes, ≥1 stretch (target: both),
`go test ./...` green with property tests, `demo.sh` exercising every feature.
