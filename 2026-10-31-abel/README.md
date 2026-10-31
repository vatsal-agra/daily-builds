# Abel — an exact computer algebra system in Go

Type `integrate((x^2+1)/(x^3+x), x)`, `factor(x^30-1)`, `limit((1+1/x)^x, x, oo)` or `eigen([[2,1],[1,2]])` and
get an **exact** answer — arbitrary-precision rationals, surds, `i`, `pi`, `e` — never a float unless you
ask for `N(...)`. Written from scratch in Go with nothing but the standard library (`math/big` for the
numbers). ~5,700 lines of Go plus ~830 lines of tests.

What makes it more than a calculator is that **Abel checks itself**: every antiderivative is
differentiated back and compared with the integrand (exactly, or at up to 60 random points), every
factorisation is multiplied back, every definite integral is cross-checked against adaptive Gauss–Legendre
quadrature, and anything it cannot do it refuses with a reason rather than guessing.

```
abel> integrate(x^2*e^x, x)
x^2*e^x - 2*x*e^x + 2*e^x
  ✓ certified: d/dx F - f simplifies to 0 exactly
abel> integrate(1/(x^2+2x+5), x)
atan(x/2 + 1/2)/2
abel> integrate(ln(x), x, 0, 1)
-1
  ✓ cross-checked against numeric quadrature
abel> integrate(e^(x^2), x)
error: no closed form found for the integral of e^(x^2) (not elementary, or beyond the implemented methods)
abel> factor(x^4+4)
(x^2 - 2*x + 2)*(x^2 + 2*x + 2)
abel> solve(x^2+2x+5=0, x)
x = -2*i - 1   ≈ -1 - 2*i
abel> limit(x*e^(-x), x, oo)
0
```

## Run it

```bash
cd 2026-10-31-abel
go run ./cmd/abel                        # REPL ('help' lists commands, 'quit' leaves)
go run ./cmd/abel -e 'diff(x^x, x)'      # one-shot
go run ./cmd/abel -f testdata/demo.abel  # script mode (one command per line, # comments)
./demo.sh                                # vet + tests + golden demo + hostile battery
```
Requires Go ≥ 1.24. No dependencies.

## Features

**1. Parser + canonical exact simplifier** (`parse.go`, `simplify.go`, `print.go`)
Precedence-climbing parser with implicit multiplication (`2x(x+3)`), `**`, decimals/scientific notation,
equations, matrices, positioned error messages with a caret, depth cap. Smart constructors keep every
expression in canonical form (equality = key comparison): like-term collection, power merging, exact
surd arithmetic via prime factorisation (`sqrt(8)+sqrt(18) = 5*sqrt(2)`, `sqrt(2)*sqrt(3) = sqrt(6)`),
rationalised conjugates (`1/(1+sqrt 2) = sqrt(2)-1`), the imaginary unit, exact trig at multiples of 30°/45°,
`e^(iπ) = -1`, `sin²+cos² = 1`, `exp/ln` cancellation, `expand`, `equal`.

**2. Symbolic differentiation** (`diff.go`) — sum/product/chain rules, general power `u^v`, every built-in function
(`sin cos tan exp ln atan asin acos sinh cosh tanh abs`), partial and n-th derivatives.

**3. Polynomial toolkit** (`poly.go`, `zassenhaus.go`, `solve.go`)
Exact `Q[x]` arithmetic, gcd, Yun square-free decomposition, **factorisation over Q by the Zassenhaus
algorithm** (mod-p distinct-degree + Cantor–Zassenhaus splitting, quadratic Hensel lifting, subset
recombination — `x^45-1` factors in 50 ms), `together`, `apart` (partial fractions by exact linear algebra),
`solve` for polynomial/rational equations and linear systems (exact through quadratics, `q(x^k)` patterns with
exact roots of unity, symbolic-coefficient quadratics, Durand–Kerner numeric roots beyond).

**4. Symbolic integration + self-certification** (`integrate.go`)
Linearity, constant extraction, a table of elementary forms with linear arguments, rational functions via exact
partial fractions (log/atan/reduction formulas, including irrational-root quadratics), `sin^m cos^n` /
`tan^n` / `sec^2k` reductions, product-to-sum, `e^{ax}·sin/cos`, tabular `P(x)·e^{ax}/sin/cos`, quadratic
radicals by completing the square, u-substitution (with rescaled-power recognition) and integration by parts
(LIATE). Definite and **improper** integrals (limits at endpoints and ±oo), refusing integrands with poles
inside the interval. Every result goes through `Verify`.

**Stretch (all shipped)**
* **Limits** (`limit.go`): substitution, L'Hôpital (with inverted-quotient retry for essential singularities),
  products → quotients, exp–log for `u^v`, conjugates for `oo-oo` radicals, one-sided limits, pole-sign analysis.
* **Taylor / Maclaurin polynomials** (`taylor(e^x/(1-x), x, 0, 4)`).
* **Exact rational matrices** (`matrix.go`): `+ - * ^`, det (also symbolic), inverse, rref, rank, nullspace,
  linear solve, Faddeev–LeVerrier characteristic polynomial (symbolic), eigenvalues with multiplicity and
  exact eigenvectors for rational eigenvalues.
* **REPL** with variables, `ans`, `vars`, script mode, numeric `N()`.

Commands: `simplify expand factor diff integrate solve gcd apart together subst taylor limit N nroots equal det
inv transpose rref rank nullspace charpoly eigen linsolve`.

## How it is tested

`./demo.sh` runs: `go vet`; 27 Go test functions including randomised **property tests** (print→parse
round-trip on 3000 random trees, commutativity/idempotence, `expand` and substitution preserve value,
`diff` vs central finite differences on 2500 random expressions, Cayley–Hamilton and `A·A⁻¹ = I` on random
matrices, solve roots re-substituted, cyclotomic factor degrees `φ(d)` for `x^n-1`, n ≤ 40, Zassenhaus
cross-checked against an independent Kronecker search); 74 integrands that must be certified; wrong
antiderivatives that `Verify` must reject; non-elementary integrals that must be refused; a golden-file
run of `testdata/demo.abel` (every feature); and 163 hostile inputs that must not trigger an internal error.
`REVIEW.md` records 25 reproduced problems from adversarial review and the fixes.

## Honest limitations

Rational integrands whose denominator has an irreducible factor of degree > 2 over Q (`1/(x^4+1)`) need
algebraic-number partial fractions; no multivariate factoring; no assumptions system (`sqrt(x^2)` stays);
`solve` is exact only through quadratics (and `q(x^k)`); `oo - oo` limits succeed only through the radical
conjugate rule; no Risch algorithm, so "no closed form found" means *not found by these methods*, not a proof.

## Why I built this today

The ledger is full of "from-scratch X" systems, but none did symbolic mathematics: Kepler *discovers* equations
numerically, Dantzig/Tarski/Horn are optimisation and logic. A CAS is the purest "every answer is checkable"
program, which let me build something with a built-in oracle (the certifier) and then use that oracle
adversarially on my own code — the property tests found two real canonical-form bugs that hand-written
cases had missed.

## Where a human could take this next

* **Algebraic numbers**: factor over Q(√2), Q(i) and finite extensions → finishes `1/(x^4+1)` and real-root radicals.
* **Risch–Norman / Risch** for a decision procedure ("provably non-elementary") and exponential/log towers.
* Cubic/quartic radicals (Cardano/Ferrari) and Galois-group-based solvability — hence the name.
* Multivariate polynomials: sparse representation, Gröbner bases, multivariate gcd/factoring.
* Series with Laurent/Puiseux expansion to make limits and `oo - oo` robust; ODE solving (`dsolve`).
* Arbitrary-precision `N(expr, digits)` with `big.Float`, LaTeX output, a web front end with step-by-step derivations.
