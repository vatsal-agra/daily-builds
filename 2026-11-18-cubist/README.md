# Cubist

A complete Rubik's Cube toolkit in Go. It solves any legal cube in about 20 moves (Kociemba's two-phase
algorithm), explains *why* an illegal cube is unsolvable, analyzes algorithms (order, cycles, parity),
and ships an animated 3-D player whose **independent physical simulation re-checks every solution in your browser**.
Standard library only — no dependencies.

## Run it
```bash
go build -o cubist .                         # Go 1.24+, no deps
./cubist solve "R U R' U' F2 D L' B2 U2 R"   # solve a scramble
./cubist solve <54-letter facelet string>    # ...or a cube given as facelets (U R F D L B order)
./cubist render -o cube.html --scramble "R U F2 D' B L2"   # standalone animated player
./cubist serve                               # web UI + API at http://127.0.0.1:8080
./cubist analyze "R U R' U'"                 # order 6, cycle structure, parity
./cubist bench -n 200                        # solve 200 random states, histogram + timings
./verify.sh                                  # everything: lint, race tests, CLI, browser, API
```
Commands: `solve scramble analyze verify show simplify invert render bench serve` (`-h` on each).
Facelet order is Kociemba's: faces U R F D L B, each read row by row as seen from outside.

## Features (7 shipped: 4 required + 3 stretch)
1. **Cubie model + notation** — corner/edge permutation & orientation, 18 moves, group multiplication, inverse,
   parser (`R2'`, `R'2`, curly quotes, parentheses; slice/wide moves rejected with a positioned error), simplifier
   (`R L R'` → `L`, cancels across commuting opposite faces).
2. **Facelet I/O + validation** — 54-letter strings ⇄ cubies with plain-language diagnoses: wrong count/letters,
   moved centres, impossible/duplicate pieces, a twisted corner, a flipped edge, a swapped pair (parity).
3. **Two-phase solver** — coordinates (twist 2187, flip 2048, E-slice 495 → 8!·8!·4!), BFS-built pruning tables
   (~0.5 s once), IDA* in both phases, keeps improving until `--target` moves or `--time`; gives up cleanly after
   a hard limit. Typical: 20.4 moves mean, ~100 ms. Short scrambles use the (simplified) inverse when shorter.
4. **3-D HTML player** (`render`) — canvas renderer written from scratch: orbit by dragging, animated layer turns,
   step/back/scrub/speed/loop, phase-labelled move chips, keyboard control, phone-friendly. Its own sticker-physics
   replays the moves and prints "✔ Verified in your browser" (or a red failure).
5. **Algorithm analyzer** *(stretch)* — order (brute force *and* from cycle structure, cross-checked), cycles with net
   twist/flip, parity, pieces changed, inverse. Known values reproduced: `R U` = 105, `R U2 D' B D'` = 1260.
6. **Random states + `bench`** *(stretch)* — uniform random legal states (perm parity fixed, free twist/flip) and
   WCA-style random-move scrambles; bench prints a length histogram and timing, re-verifying every solution physically.
7. **`serve`** *(stretch)* — web UI (type a scramble, paste facelets, or roll a random state) over a JSON API
   (`POST /api/solve`) with 422/405/503 handling, CPU-bounded concurrency, timeouts, localhost by default.

## How it's verified
Two independent cube models disagree about nothing: the algebraic cubie model is compared against a 3-D sticker
simulation (real 90° rotations in space, shares no tables) on thousands of random sequences, and *every* solver
output is replayed on the physical model (in Go, and again in JS in the browser). `verify.sh` runs 33 checks.
Honest limits are in `REVIEW.md` (two-phase is near-optimal, not optimal: superflip comes out at 21, the optimum is 20).

## Why I chose this today
The ledger had plenty of compilers, databases and simulators but nothing in permutation-group territory.
A Rubik's cube is a perfect adversarial testbed: 4.3×10¹⁹ states, strict invariants (twist, flip, parity) and a
solver clever enough to be interesting but small enough to be fully tested. Building the physics oracle first
meant I could trust every later layer.

## Where a human could take this next
- Optimal (God's-number-style) solving with a larger pattern database or symmetry reduction (Korf / Rokicki).
- Slice moves and rotations (`M E S x y z`, wide moves) in the parser and player.
- Sticker-painting editor in the UI (click-to-colour the net) and camera-based cube scanning.
- Human-method solver (CFOP/Roux) with step explanations for learners.
- WASM build so the solver runs fully client-side in the player; multi-cube (2×2, 4×4) generalisation.

## Layout
`cube/` model, facelets, coordinates, solver, physical oracle, analyzer, random · `web/` player.html + HTTP ·
`main.go` CLI · `tools/browser_check.js` · `verify.sh` · `PLAN.md` · `REVIEW.md`
