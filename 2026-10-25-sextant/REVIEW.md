# Adversarial review

Method: I tried to break the Phase 2 build as a hostile reviewer — a new fuzz harness (`tests/fuzz.cpp`, run
under ASan+UBSan) over tiny integer lattices (massively cocircular/collinear/duplicated, with 2^-30 jitter),
random segment soups (integer and float), a CLI abuse sweep (empty / one-point / duplicate / garbage / NaN /
huge / dangling-segment inputs, bad flags), scale tests (200k uniform, 90k-point grid, 100k points on a circle,
50k collinear + 1), and an independent Python `Fraction` mesh verifier that shares no code with the C++.

## Findings (all fixed)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | **High** | `sextant nearest` on an empty file **segfaulted** (exit 139): `nearest()` returned -1 and the CLI indexed `pts[-1]`. | CLI rejects empty input with a clear error; `nearest()` documented to return -1 only for empty input. |
| 2 | **High** | **O(S³) segment planarisation**: 120 random crossing segments took **113 s**, because every discovered crossing restarted an all-pairs rescan. | Grid-bucketed candidate pairs, all crossings of a round collected at once, segments split by sorted parameter; repeat to a fixed point (rounding can create new crossings). Same output, **0.024 s**. |
| 3 | **High** | CDT of a PSLG whose points are all collinear threw `cannot constrain: input points are collinear`, although that is a valid (degenerate) PSLG (fuzz: 10+ failures in 3000 cases). | Degenerate result now carries the segments as runs of consecutive chain edges. |
| 4 | Medium | Voronoi cells of near-coincident sites were clipped in absolute coordinates, so a site 2^-40 from another got a collapsed cell (non-positive area). | Clip in coordinates relative to the site, translate back at the end. |
| 5 | Medium | `polygon_area` used the shoelace formula on absolute coordinates: a 7e-10-wide cell at x≈1..2 returned area **0** (catastrophic cancellation). | Shoelace relative to the first vertex. |
| 6 | Medium | Clipping left rounding-duplicate vertices (4e-16 apart); the checker normalised such an edge's cross product by its length and reported a false "sample not inside cell". | Duplicate vertices removed relative to the cell's own extent; checker skips zero-length edges. |
| 7 | Medium | Checker demanded positive area for sliver cells and for boxes thinner than double precision resolves at those coordinates (false failures on 2-site inputs 1e-9 apart). | Tolerances now state precisely which regime is unresolvable and are documented in the README. |
| 8 | Medium | Coordinates up to 1e308 were accepted; `incircle` terms overflow (~x⁴) so the answer was luck, not exactness. | Inputs with \|coordinate\| > 1e75 are rejected with a `GeometryError` naming the limit. |
| 9 | Low | `voronoi` on empty input "failed verification"; `--margin -1` produced an inverted box `[2,0]x[3,1]`; `gen uniform abc` was parsed as 0 and reported a misleading message. | Empty input prints "0 sites"; margin validated to [0, 1e6]; `gen` count parsed strictly. |
| 10 | Low | `cdt` of an open segment chain printed "0 triangles inside the domain" with no explanation. | Prints a note that the segments enclose no region and suggests `--no-carve`. |
| 11 | Low | `gen circle N` computed 5^N before range-checking N (overflow for large N); render.cpp had a dead condition. | Check first; dead code removed. |
| 12 | Low | The in-tree checker shares the predicate implementation with the code it checks. | Added `tests/verify_mesh.py` + `--mesh` export (hex floats): an all-rational independent re-verification of orientation, manifoldness, Euler and the **global** empty-circle property. |

## Honest limitations left in (documented in README)

* Exactness covers the sign of `orient2d`/`incircle` for coordinates with |x| ≤ 1e75; differences below ~1e-75 can
  underflow inside the expansion arithmetic (not guarded).
* Voronoi vertices and CDT segment-intersection points are computed in double precision; only the *combinatorics*
  (which sites are neighbours, which triangles exist) is exact. Intersection vertices are rounded, so a split
  segment is a polyline through the rounded point.
* Voronoi cells of sites closer than ~1e-6 of the box can be slivers thinner than a double can represent.

## Fresh run-through after the fixes

`tests/fuzz.cpp` 3 seeds × 4000 iterations × 3 modes: 0 failures (ASan/UBSan clean); CLI abuse sweep: no crash,
every bad input has a one-line error and exit code 2/3; predicate differential 12 000 cases: 0 mismatches;
`verify_mesh.py` agrees on 6 generator families. None of the findings above reproduce.
