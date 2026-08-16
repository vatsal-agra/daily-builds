# Axiom — a Computer Algebra System from scratch

> **Status: Phase 3 (Adversarial review) complete.** 12 real issues found
> and fixed — see [REVIEW.md](REVIEW.md), including a working XSS
> vulnerability in the live playground, a real parser/printer round-trip
> bug, and a gap vs. the plan's own promised Bareiss-determinant
> architecture. Stretch polish (Phase 4) is next. See [PLAN.md](PLAN.md)
> for the full architecture.

## What it is (short version)

A from-scratch symbolic math engine in pure Python: parse a real math
expression, simplify it exactly (no floats in the kernel — `Fraction`-based
rational arithmetic), differentiate it, solve equations, factor polynomials,
integrate, do matrix algebra, and visualize it interactively (real LaTeX
typesetting, a live plot, a step-by-step derivation trace) in a browser.

## Try it

```
python3 -m axiom.cli demo                          # full walkthrough
python3 -m axiom.cli diff "x^2*sin(x)" --steps
python3 -m axiom.cli solve "x^2 - 5x + 6"
python3 -m axiom.cli factor "x^3 - 8"
python3 -m axiom.cli serve                          # live browser playground
```

Full feature list and verification details land here after Phase 5.
