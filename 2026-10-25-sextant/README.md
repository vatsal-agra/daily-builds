# Sextant

Exact-predicate computational geometry in C++17: Delaunay triangulation, Voronoi diagrams, convex hulls,
constrained Delaunay triangulation of PSLGs. (Work in progress — see PLAN.md for the full feature list.)

## Status

| Phase | State |
|-------|-------|
| 1 Plan | done — `PLAN.md` |
| 2 Core build | done — the four required features work end to end |
| 3 Adversarial review | done — `REVIEW.md` |
| 4 Stretch + polish | pending |
| 5 Verification | pending |
| 6 Ship | pending |

## Build and try

```
make
build/sextant gen uniform 500 > pts.txt
build/sextant delaunay pts.txt --verify --svg out.svg
build/sextant voronoi pts.txt --verify --svg vor.svg
build/sextant gen gear 12 > gear.poly && build/sextant cdt gear.poly --verify --svg gear.svg
```

Required features working so far: exact `orient2d`/`incircle` (diffed against a Python `Fraction` oracle:
`python3 tests/predicate_diff.py`), Delaunay triangulation with ghost-triangle Bowyer–Watson, Voronoi + hull +
nearest neighbour, and constrained Delaunay with segment planarisation and even-odd carving.
