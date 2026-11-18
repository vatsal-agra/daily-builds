# Cubist — PLAN

## Concept
A complete Rubik's Cube toolkit in Go: a cubie-level cube model, a **Kociemba two-phase solver**
(near-optimal solutions, typically 19–22 moves, in milliseconds after a ~1 s table build), a strict
facelet validator that explains *why* a cube is unsolvable, an algorithm analyzer, and a
self-contained animated 3D HTML player whose **independent physical simulation** re-checks the
solver's answer in the browser.

## Why it's interesting
- 4.3×10^19 states; the two-phase algorithm cuts it into two small searches (G0→G1 with
  2187·2048·495 coordinates, G1→solved with 8!·8!·4! states) guided by pruning tables built by BFS.
- Two *independent* models of the cube (algebraic cubies vs. 3-D sticker geometry) cross-check each
  other, so correctness is verified, not assumed.
- No prior ledger entry covers the cube / permutation-group territory.

## Architecture
```
cube/cube.go      cubie model (CP/CO/EP/EO), 18 moves, multiplication, inverse, notation parse/format, simplify
cube/facelet.go   54-sticker string <-> cubie, validation with human-readable diagnoses
cube/coords.go    coordinates (twist, flip, slice, cp, ud-edges, slice-perm) + setters + move tables
cube/solver.go    prune tables (BFS), two-phase IDA*, improve-until-target/time-limit
cube/physical.go  independent 3-D sticker simulation (oracle used by tests, `solve`, and CLI)
cube/analyze.go   order, cycle structure, parity, orientation of an algorithm
cube/random.go    uniform random-state generation, random-move scrambles
web/              player.html (canvas 3D, own physics) + HTTP server (`serve`) and static render
main.go           CLI: solve scramble analyze verify show simplify invert render bench serve
```

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | Cubie model + notation parser (U R F D L B, `'`, `2`), inverse, simplifier | **required** |
| 2 | Facelet I/O with validation (bad counts, impossible pieces, twisted corner, flipped edge, parity) | **required** |
| 3 | Two-phase solver with improvement loop (`--target`, `--time`) | **required** |
| 4 | Animated 3D HTML player (orbit, step, scrub, speed) with in-browser physical re-verification | **required** |
| 5 | Algorithm analyzer: order, cycles, twists/flips, parity (e.g. `R U R' U'` has order 6) | stretch |
| 6 | Uniform random-state generator + `bench` statistics (length histogram, timing) | stretch |
| 7 | `serve` mode: web UI that solves typed scrambles / pasted facelet strings via HTTP API | stretch |

## Verification plan
Go tests: group axioms, moves^4 = id, cubie vs physical oracle on thousands of random sequences,
coordinate round-trips, solver on random states, validator on hand-made invalid cubes.
`verify.sh` runs vet, tests, CLI demo with assertions and a headless-browser check of the player.
