# Axiom — a Computer Algebra System from scratch

> **Status: Phase 5 (Verification) complete.** 154 unit tests (incl. a
> `sympy` differential oracle) + a 19-check `demo.sh` walkthrough, all
> green — including the random-battery test that caught a genuine kernel
> invariant bug (see [REVIEW.md](REVIEW.md)) during this very phase.
> Final ship writeup (Phase 6) is next.

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
