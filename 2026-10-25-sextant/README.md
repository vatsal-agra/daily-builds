# Sextant

**Exact-predicate computational geometry in C++17.** Delaunay triangulation, Voronoi diagrams, convex hulls,
nearest-neighbour queries, constrained Delaunay triangulation of messy polygons, Ruppert quality meshing and
Lloyd relaxation — all built on `orient2d` / `incircle` predicates that return the *mathematically correct sign
for every double-precision input*, so the code never lies in the one place geometry code usually does.

```
$ build/sextant gen circle 6 | build/sextant delaunay - --verify --stats
36 points (0 duplicates merged), 34 triangles, 36 hull vertices, 0 flips, 0.1 ms
predicates: orient2d 204 fast / 0 exact, incircle 0 fast / 33 exact (100% exact)
verify: OK: 36 vertices, 69 edges, 34 triangles, 36 hull edges, angles 2.17474..171.87 deg
```
(36 lattice points lie exactly on one circle. Every `incircle` is a tie, and every tie is decided exactly.)

## Run it

Needs `g++` (C++17) and `make`; Python 3 and Node + Playwright are optional (tests / browser check only).

```
make                                   # builds build/sextant
./demo.sh                              # guided tour of every feature, writes pictures + viewers to out/
./verify.sh                            # everything: ~100 s, ends with ALL GREEN
```

```
sextant gen <kind> [N] [--seed S]      uniform grid circle cluster spiral line degenerate | star gear annulus pentagram comb lshape
sextant delaunay <pts>                 Delaunay triangulation
sextant voronoi  <pts> [--margin F]    Voronoi cells clipped to a box
sextant hull     <pts>                 exact convex hull (cross-checked against the triangulation boundary)
sextant cdt      <pslg> [--no-carve]   constrained Delaunay triangulation
sextant refine   <pslg> [--angle 25] [--area A] [--max-points N]
sextant lloyd    <pts> [--iters 20] [--out FILE]
sextant nearest  <pts> X Y
sextant check    <file>                build, then run the full independent certificate
options: --svg FILE  --html FILE (interactive viewer)  --mesh FILE (exact dump)  --verify  --stats
```
`<file>` may be `-` for stdin. Input format: one `x y` per line; a PSLG adds `s i j` lines (0-based vertex indices);
`#` starts a comment.

```
build/sextant gen gear 10 > gear.poly
build/sextant refine gear.poly --angle 30 --area 0.002 --verify --html gear.html
#  refined 50 -> 1736 triangles with 918 Steiner points (150 on segments); angles 30.01..119.78 deg
#  verify: OK ...; segments encroached by a vertex: 0
```
Open `out/refine-gear.html` for the viewer: pan/zoom, hover any triangle for its angles, circumcircle and
circumradius/shortest-edge ratio, toggle layers (quality colouring, Voronoi cells, segments, hull), light/dark.

## Features

| # | Feature | How it is verified |
|---|---------|--------------------|
| 1 | **Exact adaptive predicates** — floating-point filter, then Shewchuk-style expansion arithmetic (error-free `two_sum`/`two_product` via `fma`, expansion sum/scale/product) | 20,000 adversarial cases (near-collinear/cocircular within a few ulps, lattice ties, 1e-30…1e30 scales) vs a Python `Fraction` oracle: 0 mismatches |
| 2 | **Delaunay triangulation** — Bowyer–Watson with *ghost triangles* (vertex −1 = infinity, so the hull needs no special case), Morton-ordered insertion, stochastic walk location, exact cavity tests; duplicates, collinear and cocircular input handled | independent checker (CCW, adjacency, Euler, local + global empty-circle) and an all-rational Python verifier; ASan/UBSan fuzz on lattices with 2⁻³⁰ jitter; 200k points in 0.5 s |
| 3 | **Voronoi diagram, convex hull, nearest neighbour** — cells from the Delaunay neighbours clipped to a box (in site-relative coordinates, so near-coincident sites keep precision); exact monotone-chain hull; greedy descent on the Delaunay graph | cell areas tile the box, convexity, sampled nearest-site agreement; hull vs triangulation boundary; 10,000 NN queries vs brute force |
| 4 | **Constrained Delaunay triangulation** of arbitrary PSLGs — grid-accelerated planarisation of crossing segments, vertices on segments split them, Sloan edge-flip insertion, even-odd carving of holes and self-crossing outlines | every segment is realised, local-Delaunay across unconstrained edges, area checks (annulus = 12, L-shape = 5), 3-mode random fuzz |
| 5 | **Ruppert refinement** (stretch) — encroached-segment splitting, circumcentre insertion, minimum-angle and maximum-area targets, buffer box so hull segments split safely, Steiner-point cap | min angle ≥ target on shapes with ≥ 60° corners, area preserved, **no segment encroached afterwards**, 195k-triangle mesh in 2 s |
| 6 | **Interactive HTML viewer** (stretch) — one self-contained file, canvas, light/dark, phone layout, angle histogram | headless Chromium: no console errors, no external requests, canvas painted, hover + toggles work |
| 7 | **Lloyd relaxation** (stretch) — centroidal Voronoi iteration with exact cell energy | energy never increases; cell-area spread shrinks ≥ 4× |
| 8 | **`check` / `--verify`** (stretch) — certificate of any triangulation, itself tested by corrupting meshes and demanding rejection | unit tests flip a Delaunay edge / reverse a triangle and require failure |

## How it works (short)

* `src/expansion.hpp`, `src/predicates.cpp` — a filtered predicate: evaluate in doubles with a forward error bound
  (`3ε` orient, `10ε` incircle); if the bound cannot certify the sign, redo it exactly with expansions. On random
  data 0% of calls reach the exact stage; on a lattice 100% of the `incircle` ties do — and are still decided correctly.
* `src/triangulation.*` — one `Tri{v[3], n[3], con, inside}` array. Hull edges carry a ghost triangle `(b,a,-1)` on
  their right, so the mesh is a closed surface and insertion, flipping and cavity growth are uniform. A ghost's
  "circumcircle" is the open half-plane right of its hull edge plus the open edge itself.
* `src/refine.cpp` — Ruppert's algorithm; a segment is encroached iff an adjacent in-domain triangle's apex lies in its
  diametral circle (true in a CDT), checked incrementally from the triangles each operation touched.
* `src/check.cpp` + `tests/verify_mesh.py` — two independent certifiers (the second shares *no code* with the first).

## Honest limits

* Exact signs hold for |coordinate| ≤ 1e75 (larger input is rejected with an error, not silently mis-handled);
  coordinate *differences* below ~1e-75 can underflow inside the expansions and are not guarded.
* Only the combinatorics are exact. Voronoi vertices, circumcentres and the intersection points of crossing
  segments are computed in doubles (a split segment becomes a polyline through the rounded point).
* Cells of sites closer than ~1e-6 of the box can be slivers thinner than a double can represent at absolute coordinates.
* Ruppert's 20.7° guarantee needs input angles ≥ 60°. Sharper input still improves but may miss the target; `refine`
  says so, and a Steiner-point cap guarantees termination. Segment midpoints are rounded, so a refined boundary is
  the original polygon up to one ulp.
* Lloyd relaxation in a box leaves boundary sites hugging the box edge (the true CVT behaviour), giving sliver
  triangles along it.
* Single-threaded, in-memory; ~1M points is the practical ceiling.

## Why I chose this today

The repo's ledger had parsers, compilers, VMs, filesystems, networks, crypto, databases and ML — but nothing in
**computational geometry**, where the interesting engineering problem is not the algorithm but *robustness*: a
triangulator built on `double` predicates loops or corrupts itself on exactly the inputs real data contains
(lattices, duplicates, sensor grids). Building the predicates first and proving everything downstream against
independent oracles made it a project where "it works" is a checkable claim, not a feeling.

## Where a human could take this next

* **Delaunay deletion and incremental updates** (moving points, streaming insert/delete) and a dynamic point-location structure.
* **3D**: orient3d / insphere are the same expansion machinery; Delaunay tetrahedralisation is the natural sequel.
* **Shewchuk's concentric-shell segment splitting** to make Ruppert terminate on small input angles, and
  off-centre/"Üngör" Steiner points for ~35% fewer triangles.
* **Exact construction of intersection points** with rational/expansion coordinates instead of rounded doubles.
* Voronoi with **weights (power diagrams)**, **Fortune's sweepline** as an independent algorithm to cross-check, polygon boolean
  operations on top of the CDT, a WASM build of the library behind the viewer so the browser can triangulate live.

## Layout

```
PLAN.md REVIEW.md README.md  Makefile  demo.sh  verify.sh
src/        expansion.hpp predicates.* triangulation.* voronoi.* refine.cpp check.* io.* render.* viewer.cpp main.cpp
tests/      unit.cpp fuzz.cpp cli_tests.sh predicate_diff.py pred_cli.cpp verify_mesh.py browser_check.js
out/        example SVGs and interactive HTML viewers produced by demo.sh
```
