# Tangle (in progress)

Knot-theory laboratory in pure Python (stdlib only): give it a braid word, PD code,
catalog name or torus knot; get the Jones polynomial, Alexander polynomial, determinant,
Fox colorings, an identification against its own catalog, unknot proofs, and SVG drawings.

```
python3 -m tangle analyze --name 5_2
python3 -m tangle analyze --braid "1 -2 1 -2"
python3 -m tangle analyze --pd "X[1,4,2,5] X[3,6,4,1] X[5,2,6,3]"
python3 -m tangle simplify --braid "1 2 -1 -2"
python3 -m tangle draw --name 6_3 -o 6_3.svg
python3 -m tangle scramble --name 6_3 --steps 25 --seed 2
python3 -m unittest discover -s tests
```

## Status
- **Phase 1 (plan)** done — see PLAN.md.
- **Phase 2 (core build)** done: diagram model (braid + PD, orientation, signs), Jones via
  frontier-DP Kauffman bracket, Alexander/determinant/Fox colorings, catalog + identification.
  Also already in: braid simplifier, SVG renderer, scrambler, Conway/plat constructor.
- **Phase 3 (adversarial review)** done — REVIEW.md lists 13 findings (non-planar PDs accepted,
  wrong link colorings, orientation-fragile link identification, ...); all fixed and pinned by
  `tests/test_review.py`.
- Phases 4-6 (stretch + polish, verification, ship) pending.
