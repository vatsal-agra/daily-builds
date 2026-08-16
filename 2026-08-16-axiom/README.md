# Axiom — a Computer Algebra System from scratch

> **Status: Phase 2 (Core build) complete.** All 4 required features plus
> both planned stretch features (and a bonus 3rd) are implemented and
> working end-to-end. Adversarial review (Phase 3) and final polish are
> next. See [PLAN.md](PLAN.md) for the full architecture.

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
