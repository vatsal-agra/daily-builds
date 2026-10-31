# Abel — a computer algebra system in Go

Exact symbolic mathematics from scratch (Go stdlib only, `math/big`).

**Status: Phase 2 (core build) complete.** The four required features work end-to-end:

1. Parser + canonical exact simplifier (rationals, surds, `i`, `pi`, `e`)
2. Symbolic differentiation
3. Polynomial toolkit: expand, gcd, factor over Q, solve, partial fractions
4. Symbolic integration with self-certification (+ definite integrals)

Run: `go run ./cmd/abel` (REPL), `go run ./cmd/abel -e 'integrate(x*sin(x), x)'`.
Plan: see PLAN.md. Full README arrives in the final phase.

**Phase 3 (adversarial review) complete** — see REVIEW.md: 22 reproduced problems fixed (Zassenhaus
factoring replaced a Kronecker search that took 10 s on `x^30-1`; several integration gaps closed; four
silent-lie bugs removed), plus a short list of loud, documented limitations.

**Phase 4 (stretch + polish) complete** — added stretch features on top of Taylor series and exact matrices:
a **limits engine** (direct substitution, L'Hôpital incl. inverted-quotient retry, product→quotient, exp–log
for powers, pole sign analysis, limits at ±oo) which in turn powers **improper definite integrals**
(`integrate(ln(x), x, 0, 1)` = -1, `integrate(1/(1+x^2), x, -oo, oo)` = pi); input-error handling hardened
(positioned parse errors, depth cap, panic recovery, honest refusals).
