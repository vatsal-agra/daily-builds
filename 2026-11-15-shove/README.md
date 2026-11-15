# Shove — a Sokoban toolkit

Parse puzzles, **solve them with a proven push-optimal A\***, **generate new ones by playing the game backwards**,
**verify any move string**, and **export a polished single-file HTML game** whose levels ship with machine-verified
solutions and an in-browser hint solver. Go, stdlib only (the browser test uses Playwright, optional).

`examples/shove-game.html` is a ready-to-open build (14 levels). Open it in any browser.

## Run it
```bash
go build -o shove ./cmd/shove

./shove solve levels/starter.txt              # optimal pushes + LURD move string for every level
./shove solve levels/generated.txt -n 10      # one level
./shove gen -w 10 -h 9 -boxes 5 -seed 7 -min-pushes 15      # new level, rated by the solver
./shove pack -count 8 -w 12 -h 10 -boxes 6 -walls 0.22 -nodes 400000 -o my-pack.txt   # easy -> hard pack
./shove check levels/starter.txt "dlUrrrdLullddrUluRuulDrddrruLdlUU" -n 1   # verify a solution
./shove replay levels/starter.txt -n 3        # ASCII animation (-delay 0 prints every frame)
./shove html levels/starter.txt my-pack.txt -o game.html   # playable game, solutions verified at export
./shove bench levels/generated.txt --ablate -nodes 30000   # stats + heuristic/deadlock ablation
./demo.sh                                     # everything above, with assertions
go test ./...                                 # unit + brute-force oracle tests
node tests/browser.test.js game.html          # headless Chromium end-to-end suite
```
Pack format is plain XSB: `#` wall, `@` player, `+` player on goal, `$` box, `*` box on goal, `.` goal; levels separated
by blank lines; a `;name` line directly above a map names it.

## Features
1. **XSB parser/validator** — CRLF, packs, names, precise `line N: level K:` errors (box/goal count, one player, illegal
   characters, not enclosed by walls, boxes on the grid edge).
2. **Push-optimal solver** — A\* over *(box set, canonical player region)*; admissible heuristic = min-cost box↔goal
   assignment (Hungarian) over precomputed single-box push distances; dead-square table from reverse BFS; recursive
   **freeze-deadlock** detection; node/time/memory budgets with distinct `unsolvable` vs `budget` outcomes. Every answer
   is re-checked by the independent replayer before it's printed.
3. **Reverse-play generator** — start from a *solved* room, apply random legal **pulls**, so every candidate is solvable
   by construction; the solver rates each and the hardest of N (by search effort) wins. Seeded and byte-for-byte
   deterministic.
4. **Playable HTML game** — canvas renderer, keyboard/WASD/swipe, undo, restart, live **deadlock warning** (JS port of the
   same dead-square + freeze logic), level select, per-level personal bests, solution playback with speed control,
   responsive layout.
5. *(stretch)* **Verifier + ASCII replay** (`check`, `replay`).
6. *(stretch)* **Bench** table (text/markdown) with `--ablate`: re-runs each level without the matching heuristic / without
   freeze pruning.
7. *(stretch)* **Pack builder** (`pack`) sorting generated levels by measured difficulty.
8. *(stretch)* **Hint button** — a second, independent A\* + Hungarian solver written in JavaScript runs in the browser from
   *your current position* and animates the next push. Its optimal push counts agree with the Go solver on all 14 shipped levels.

## How it's verified
* `sok/diff_test.go` — an **unpruned brute-force oracle** (plain BFS, no heuristic, no deadlock logic) agrees with the solver
  (full, no-freeze, no-matching variants) on optimal push counts for 250 random generated levels; a heavier 3–5-box run
  of 250 also agreed. Reverse-play never produced an unsolvable level.
* 15 Go tests: parser, replay rules, dead squares, freeze deadlocks, admissibility, determinism, generator validation, HTML escaping…
* `tests/browser.test.js` — 14 browser assertions (all embedded solutions replay in the page's rules engine, JS A\* ≡ Go optimum,
  real key events, deadlock warning, Ctrl+R not hijacked, peeking at the solution isn't "solving", Hint works, no horizontal scroll on phones).
* `demo.sh` — 17 explicit CLI/HTML checks, all green.
* Heuristic ablation (bench, budget 30k nodes): the Hungarian bound solves every shipped level; sum-of-nearest-goal blows the budget on
  4 of the last 5, and freeze pruning trims expansions only a few percent on these fairly open levels (it matters more on tight ones; the oracle test shows it never costs optimality).

## Why I chose this today
Nothing in the ledger touched puzzle search. Sokoban is a perfect small-but-deep problem: PSPACE-complete, so a solver is
real engineering (deadlocks decide everything), and *generating* levels is the interesting inverse problem — random layouts
are almost never solvable, but pulling boxes backwards from a solved state is solvable by construction. Two independent
solvers (Go + JS) and a brute-force oracle make correctness checkable rather than hoped for.

## Limits (honest)
* Optimal in **pushes**; walking moves are not minimised.
* No PI-corral / tunnel macros / bipartite deadlocks, so the hardest competition levels (≥10⁷ states) are out of reach;
  budget ≈ 10⁶ expansions in a few seconds.
* Generated levels are "hard for the solver", which isn't always "fun for a human" (they are often open and a bit random).

## Where a human could take this next
* Add **move-optimal** search (state = exact player cell) as a second mode, or a push-then-move lexicographic refinement.
* PI-corral pruning, tunnel/goal-room macros, and pattern databases — the classic route to solving Sokoban-XL.
* A generator objective tuned for *human* difficulty (number of pushes in forced sequences, branching of the solution) and
  symmetry/aesthetics filters; community-level import (`.sok`/SLC) and a Rust/WASM port of the solver so Hint handles every level.
* Sharing: encode a level + best solution in a URL; a daily seeded puzzle.

Layout: `sok/` library · `cmd/shove/` CLI · `levels/` packs · `tests/` browser suite · `examples/` built game · PLAN.md · REVIEW.md
