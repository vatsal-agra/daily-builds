# Morphica — Generative Algorithmic Art Engine

## Concept
A from-scratch system for producing diverse families of algorithmic art — each
rooted in a distinct area of mathematics: formal grammars, reaction kinetics,
nonlinear dynamics, and computational geometry.  The goal is a single cohesive
CLI that can render stills, animate, and serve an interactive browser viewer,
all with no external dependencies (pure Python 3 stdlib + optional numpy for
the RD simulation hot path, falling back to pure-Python if absent).

## Why It's Interesting
Most "generative art" libraries are thin wrappers around an existing canvas.
Here every algorithm is implemented from scratch:
- The turtle-graphics rasteriser and SVG emitter are hand-rolled
- The reaction-diffusion solver uses a hand-coded discrete Laplacian
- The attractor renderers implement their own histogram-density coloring
  (flame-algorithm style), not just scatter plots
- The Voronoi engine uses Fortune's sweep-line algorithm

## Architecture

```
morphica/
  cli.py           — top-level argument dispatch
  lsystem.py       — L-system rewriting + turtle geometry → paths
  reactiondiff.py  — Gray-Scott PDE solver + concentration → palette
  attractors.py    — ODE/map integrators + density accumulator
  voronoi.py       — Fortune's sweep-line + Lloyd relaxation + stippling
  palette.py       — named colour palettes, gradient mapping, HSV cycling
  png_encoder.py   — hand-rolled PNG (IHDR/IDAT/IEND, zlib, Sub filter)
  svg_builder.py   — minimal SVG serialiser (paths, rects, polylines)
  viewer.py        — self-contained single-file HTML interactive viewer
  tests/           — unit + integration tests (unittest, no deps)
  demo.sh          — end-to-end exercise of all features
  README.md
  REVIEW.md
```

## Feature List

### Required (4)
1. **L-System Engine**
   - Rewrite engine for context-free parametric rules, any number of steps
   - Turtle interpreter producing SVG line paths (angle, step, push/pop stack)
   - ≥8 built-in named presets: Sierpinski triangle, Koch snowflake, Dragon
     curve, Barnsley fern, Bush, Hilbert curve, Pentigree, Fractal plant
   - Stochastic variants (rule chosen probabilistically)

2. **Reaction-Diffusion (Gray-Scott)**
   - Configurable Du, Dv, F, k parameters
   - ≥6 named parameter presets producing visually distinct patterns
     (coral, mitosis, worms, maze, spots, fingerprint)
   - Outputs concentration field → colour map → PNG
   - Pure-Python fallback (no numpy required, slower)

3. **Strange Attractors**
   - Lorenz, Rössler, Clifford (2-D map), DeJong, Pickover, Duffing attractors
   - Histogram-density accumulator: each pixel tallies how many orbit
     points land in it; colour = log-scaled density mapped through a palette
   - Renders at arbitrary resolution
   - Auto-discovers interesting parameter ranges via a quick trial run

4. **Voronoi Diagram + Weighted Stippling**
   - Fortune's sweep-line Voronoi for arbitrary point sets
   - Lloyd relaxation (centroidal Voronoi tessellation) for uniform spacing
   - Weighted stippling: point density follows a luminance target image
     (supplied as a built-in gradient or external pixel data)
   - SVG and PNG output modes

### Stretch (3+)
5. **Interactive Browser Viewer** — single-file self-contained HTML with a
   JS canvas that can run L-system and attractor animations frame-by-frame,
   export frames, scrub timeline.
6. **Palette System** — 12+ named palettes, palette cycling over time,
   histogram equalization, divergent colour maps, per-channel gamma.
7. **Animation / Frame Export** — render N-frame sequences (e.g. RD time
   evolution, attractor orbit building up, L-system growing step-by-step)
   and either serve them as SSE stream or write numbered PNGs.

## Implementation Notes
- PNG encoder: IHDR (8-bit RGBA), one IDAT chunk, Sub filter per row, zlib
  deflate from stdlib.
- SVG builder: minimal serialiser, no XML libs.
- RD solver: explicit Euler on a 2-D grid with wrap-around boundary; numpy
  vectorised if available, otherwise pure-Python nested loop (slower).
- Fortune's algorithm: parabola / beach-line sweep with priority queue;
  half-edge DCEL output.
- Attractor histogram: flat `bytearray` accumulator, log-normalise, map
  through palette, encode PNG.
- All randomness seeded via `--seed` for reproducibility.
