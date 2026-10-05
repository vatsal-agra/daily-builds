# Mosaic — PLAN

## Concept
Mosaic is a from-scratch **Wave Function Collapse (WFC)** engine in Rust (zero dependencies).
Give it a small example image, or a tileset with edge sockets, and it synthesises arbitrarily
large outputs that are *locally indistinguishable* from the input: every NxN window of the
output exists in the sample (overlapping model), or every pair of neighbouring tiles agrees on
the socket they share (tiled model).

## Why it's interesting
WFC is constraint satisfaction dressed as art: each cell is a superposition of candidate
patterns, we repeatedly *observe* the lowest-entropy cell, and arc-consistency *propagation*
prunes neighbours. The classic implementation just restarts on contradiction. Mosaic instead
keeps a **trail + decision stack** so contradictions are repaired by chronological
backtracking (undo to the last decision, forbid the failed choice, propagate again) — this
turns WFC into a small complete-ish CSP solver and we can benchmark how much it helps.

## Architecture
```
src/
  main.rs      CLI (overlap | tiled | bench | list)
  rng.rs       xorshift64*/splitmix PRNG, deterministic by seed
  solver.rs    generic WFC core: wave, support counts, entropy, propagate, trail, backtracking
  overlap.rs   overlapping model: pattern extraction, symmetries, overlap-agreement adjacency, rendering
  tiled.rs     tiled model: tiles with edge sockets, rotations, socket compatibility, rendering
  tilesets.rs  procedurally drawn tilesets (circuit, terrain Wang tiles)
  samples.rs   built-in ASCII sample images + loader for .txt / PPM samples
  png.rs       from-scratch PNG encoder (CRC32, Adler32, stored deflate) + base64
  anim.rs      collapse-animation recorder -> self-contained HTML flipbook
  verify.rs    independent output validators (used by tests and CLI --verify)
tests/         integration tests
demo.sh        runs every feature end to end
```
The solver is model-agnostic: a model supplies `T` patterns, weights and a directional
propagator table; the solver does the rest.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **Generic WFC solver core**: min-entropy observation with noise, support-count propagation, weighted collapse, periodic/non-periodic grids | **required** |
| 2 | **Overlapping model**: NxN pattern extraction from sample, up-to-8-fold symmetry augmentation, overlap-agreement adjacency, wrap-around input option, "ground" row anchoring, partial-superposition rendering | **required** |
| 3 | **Simple tiled model**: tiles with edge sockets (symmetric and paired `+`/`-` sockets), auto rotations, weights; built-in `circuit` tileset and a 81-tile 3-level `terrain` Wang-tile set drawn procedurally | **required** |
| 4 | **Backtracking**: trail-based undo + decision stack, contradiction recovery, restart budget, stats (decisions, backtracks, restarts) | **required** |
| 5 | **Pinned cells / constraints**: force a cell to a colour (overlap) or tile (tiled) before solving | stretch |
| 6 | **Collapse animation**: HTML flipbook with entropy-averaged partial colours, including visible backtracks | stretch |
| 7 | **Benchmark mode**: success-rate/time of backtracking vs restart-only over N seeds | stretch |
| 8 | **Output validators**: independently verify every window / every edge pair of an output | secondary |
| 9 | PNG export (own encoder), ASCII export, scale factor | secondary |
