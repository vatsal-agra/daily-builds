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
