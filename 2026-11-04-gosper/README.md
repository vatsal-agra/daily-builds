# Gosper — a Hashlife cellular-automaton laboratory

Gosper is a from-scratch implementation of Bill Gosper's **Hashlife** algorithm (Go, standard library
only) generalised to *any* two-state Life-like rule (B/S notation). A hash-consed quadtree memoises the
future of every square of cells, so Gosper can jump a glider gun **2^40 generations (a trillion) in
~10 ms**, then analyse, census, render and report on the result.

```
$ gosper run gosper-gun -gens 2^40 -o gun.mc
gosper-gun  rule B3/S23  generation 1,099,511,627,776
population: 183,251,938,004
nodes:      12,170   hits 58,743  misses 12,070   time 6ms

$ gosper analyze acorn
fate:       population settles into period 1 from generation 5,206 (peak 1,057 at gen 4,408, then 633)
look-ahead: Hashlife jumped to generation 16,777,216: population 633, predicted 633 — CONFIRMED
```

## Run it
```
go build -o gosper .
./gosper patterns                         # built-in library
./gosper info rpentomino
./gosper run acorn -gens 5206 -show -o acorn.rle     # -o: .rle / .cells / .mc (Macrocell)
./gosper analyze gosper-gun               # period / speed / settling / growth class
./gosper census -soups 2000               # what do random 16x16 soups turn into?
./gosper render gosper-gun -gens 2^36 -o gun.png
./gosper report acorn -o acorn.html       # self-contained HTML report
./gosper verify -n 300                    # Hashlife vs independent naive simulator
./verify.sh                               # everything: fmt, vet, tests, CLI walk-through, headless browser
```
`<pattern>` is a built-in name, a `.rle` / `.cells` / `.mc` file, or `-` for stdin. Rules: `-rule B36/S23`
(also `S23/B3`, `23/3`). Generation counts accept `1000`, `1e9`, `2^40`. Any gen count up to 2^56 works.

## Features
**Required**
1. **Hashlife engine** — hash-consed quadtree, memoised `result(node, 2^j)`, any non-B0 B/S rule, any step
   size (binary decomposition), auto-expanding/shrinking universe, compaction GC, hard node budget that fails
   gracefully on chaotic patterns instead of eating RAM.
2. **Pattern I/O** — RLE (with rule header), plaintext `.cells`, Golly-style Macrocell read+write (a
   trillion-generation gun is an 850-line file), 14 built-in patterns.
3. **Independent oracle + differential `verify`** — a sparse-set simulator shares no code with the engine;
   random soups × named/random rules × random step schedules (incl. forced compaction) are compared cell by cell,
   plus RLE/Macrocell round-trips.
4. **Analyzer** — exact period + displacement + speed (`1c/4 diagonal`), still/oscillator/spaceship/dies
   classification, settling generation of methuselahs with a Hashlife *look-ahead* check, population at any
   generation, exact bounding box, and a log–log growth fit (bounded / linear / quadratic).

**Stretch (all shipped)**
5. **Soup census** — parallel, deterministic random-soup ash census; clusters objects and names them
   (block, beehive, loaf, glider, …) invariant to phase, rotation and reflection.
6. **PNG renderer** — crisp cells zoomed in; zoomed out it shades from node populations, so a
   183-billion-cell universe renders instantly.
7. **HTML report** — snapshots, per-generation and log–log population charts, verdict cards; light/dark,
   phone width, checked in headless Chromium.

## Verified facts (all asserted in `verify.sh`)
R-pentomino stabilises at gen 1103 with 116 cells; acorn at 5206 with 633; diehard dies at 130; glider is
1c/4 diagonal; LWSS 2c/4; pentadecathlon p15; Gosper gun population density is exactly 1/6 of the generation
(one glider per 30 generations); census most-common object is the block.

## Why this today
Nothing in the ledger touched cellular automata, and Hashlife is the rare algorithm whose payoff is almost
absurd: exponential time compression from nothing but hash-consing and memoisation. It also makes a great
testbed for honest verification — a fast, clever engine is only believable next to a dumb independent oracle
(which, amusingly, was the thing that turned out to be buggy first; see REVIEW.md).

## Layout
`life/` library (universe, naive, rle, patterns, analyze, census, render, report + tests), `main.go` /
`cmds*.go` CLI, `verify.sh`, `check_report.js`, PLAN.md, REVIEW.md.

## Where a human could take this next
* Multi-state / Generations rules and non-totalistic (Hensel isotropic) rules; B0 via even/odd generation trick.
* Interactive zoom/pan web viewer using the same quadtree renderer (WASM build of `life/`).
* Glide-reflection spaceship detection, ship-collision (glider-synthesis) search, and a real apgsearch-style
  census with hash-census upload.
* Garden-of-Eden / predecessor search via SAT, and pattern search (gun/puffer finders) using the analyzer as the fitness function.
* Parallel hop evaluation and a smarter GC (reference counting, generational node tables).
