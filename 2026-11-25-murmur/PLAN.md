# Murmur — Plan

## Concept
A flocking laboratory. Reynolds boids are easy to draw and hard to *measure*. Murmur is a
deterministic, seeded flocking engine plus the instruments to treat it as a physical system:
order parameters, phase-transition sweeps, a metric-vs-topological neighbourhood comparison
(the finding from the starling studies by Ballerini et al. 2008), predator–prey experiments,
and a genetic tuner that *evolves* flock parameters. A browser UI lets you watch and poke it live.

## Why it's interesting
- Collective motion shows a genuine noise-driven order→disorder transition. The sweep tool plots it.
- Starlings interact with their ~7 nearest neighbours, not everything within a radius. The
  topological mode lets us test whether that makes a flock robust to density change; metric flocks fragment.
- One engine file (`engine.js`) runs identically in Node (tests, CLI) and in the browser (UI).

## Architecture
- `engine.js` — UMD module: PRNG (mulberry32), uniform-grid spatial hash with torus wrap, exact kNN by ring
  expansion, Flock class (steering, predators, obstacles, boundaries), metrics (polarization, angular
  momentum, NN distance, union-find clusters), state hash, snapshot/restore.
- `tools.js` — noise sweep, density sweep, GA tuner, SVG plotting, experiments built on the engine.
- `murmur.js` — CLI: `run`, `sweep`, `compare`, `tune`, `bench`, `replay`.
- `index.html` — canvas UI (sliders, live charts, predator/obstacle placement, trails).
- `test/` — node:test suite; `demo.sh` end-to-end run.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Seeded boids engine: separation/alignment/cohesion, torus & walled boundaries, grid spatial hash proven equal to brute force | **required** |
| 2 | Neighbourhood modes: metric radius vs topological k-nearest (exact kNN on torus) | **required** |
| 3 | Instruments: polarization, angular momentum, NN distance, cluster count/largest fraction, time series; noise sweep CLI → CSV + SVG phase-transition plot; metric-vs-topological density-robustness experiment | **required** |
| 4 | Predators + obstacles: pursuit/evasion, catches, circular obstacle avoidance, with measured catch rates | **required** |
| 5 | Genetic tuner evolving flock parameters against a fitness (cohesion, order, no collisions, survival) | stretch |
| 6 | Deterministic snapshot / replay with state-hash verification | stretch |
| 7 | Interactive browser UI with live sliders, trails, charts | stretch |
