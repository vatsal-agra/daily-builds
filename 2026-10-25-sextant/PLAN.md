# Sextant — plan

## Concept
A from-scratch **computational-geometry toolkit in C++17** whose foundation is *exact* arithmetic:
Shewchuk-style floating-point expansions decide `orient2d` and `incircle` correctly for every
double-precision input, so everything built on top (Delaunay triangulation, Voronoi diagrams, convex
hulls, constrained triangulations, quality meshes) is combinatorially correct even on the inputs that
break naive geometry code: cocircular grids, collinear runs, duplicates, near-degenerate slivers.

## Why it's interesting
Geometry code fails in the one place nobody tests: when a floating-point predicate lies. A triangulation
built on a wrong `incircle` answer can loop forever, produce overlapping triangles or crash. Sextant makes
the predicates exact (with a fast filter so the common case costs a few flops) and then *proves* every
output with independent checkers that use those same exact predicates plus a Python `fractions.Fraction`
oracle that shares no code with the C++ side.

## Architecture
```
src/expansion.hpp   error-free transforms (two_sum, two_product via fma) + expansion sum/scale/compress
src/predicates.*    orient2d / incircle: static filter -> exact expansion fallback; sign only
src/mesh.*          triangle mesh with ghost triangles (vertex -1 = infinity), adjacency, flips, walk
src/delaunay.*      Bowyer-Watson insertion with ghost triangles, Morton-ordered, duplicate handling
src/voronoi.*       dual graph, cells clipped to a box, convex hull, nearest-neighbour queries
src/cdt.*           PSLG -> planarised segments -> segment insertion by flips -> even-odd carving
src/refine.*        Ruppert refinement (encroached segments, circumcentres, min-angle guarantee), Lloyd
src/check.*         independent validators (orientation, adjacency, empty-circle, Euler, constraints)
src/io.*, render.*  point / .poly readers, SVG + self-contained interactive HTML writers
src/main.cpp        CLI: gen, delaunay, voronoi, hull, cdt, refine, lloyd, nearest, check, predicates
tests/              unit tests, Python Fraction oracle, differential + degenerate fuzz, browser check
```

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | **Exact adaptive predicates** `orient2d`, `incircle` (filter + expansion arithmetic), verified against a Fraction oracle on adversarial near-degenerate inputs | **required** |
| 2 | **Delaunay triangulation** (ghost-triangle Bowyer-Watson; duplicates, collinear, cocircular, all-collinear sets) with exact empty-circle certificate | **required** |
| 3 | **Voronoi diagram + convex hull + nearest-neighbour queries** derived from the triangulation, cells clipped to a bounding box | **required** |
| 4 | **Constrained Delaunay triangulation** of a PSLG: crossing segments are planarised, collinear vertices split segments, even-odd carving of holes | **required** |
| 5 | **Ruppert quality refinement** with a minimum-angle target and area bound | stretch |
| 6 | **Self-contained interactive HTML/SVG viewer** (layers, pan/zoom, hover inspection, light/dark) | stretch |
| 7 | **Lloyd relaxation** (centroidal Voronoi) | stretch |
| 8 | Independent **`check` command** that certifies any mesh file | stretch |

Done = all 4 required + at least 1 stretch, each exercised by `verify.sh`.
