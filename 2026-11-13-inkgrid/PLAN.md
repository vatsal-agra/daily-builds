# Inkgrid — Plan

## Concept
Inkgrid is a complete nonogram (Picross / Griddlers) studio: a dependency-free
solver engine, a generator that **guarantees unique, logically rated puzzles**,
a polished playable web UI with *explaining* hints, and a CLI. Everything runs
from one portable engine (`src/engine.js`) that works unchanged in Node and in
the browser (opened straight from `file://`).

## Why it's interesting
Nonograms are NP-complete, yet most puzzles are solvable by pure line logic.
The interesting engineering is in (1) an O(n·k) per-line DP that deduces every
forced cell at once, (2) telling "solvable by logic" from "needs guessing" so
difficulty is *measured*, not guessed, and (3) generating puzzles that look
like pictures yet have exactly one solution, by repairing ambiguity using the
second solution the solver finds.

## Architecture
```
src/engine.js   UMD, no deps: clues, lineSolve (DP), propagate, solve (counts
                solutions, depth-limited probing, rating), PRNG, generator,
                .non/JSON parse+serialise, image->grid thresholding
cli.js          node cli.js solve|gen|rate|render
index.html      UI shell          style.css  theme
app.js          game state, input, hints, solver visualiser, import/share
test/run.js     test suite + feature demo (node test/run.js)
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Line-solver DP: given a clue and a partially known line, returns every cell forced filled/empty, or reports contradiction | **required** |
| 2 | Full solver: propagation to fixpoint, then backtracking; counts solutions (up to a limit) to prove uniqueness | **required** |
| 3 | Difficulty rating: classifies puzzles as line-logic / probing (1-level contradiction) / guessing, with a numeric score | **required** |
| 4 | Generator: seeded, blob-shaped pictures at chosen size & density, repaired until the solution is unique and meets the requested difficulty | **required** |
| 5 | Playable UI: drag-fill, X-marking, live clue completion, mistake check, undo/redo, timer, win detection | **required** (UI is part of game) |
| 6 | Explaining hints: finds a line where logic forces a cell from the player's *current* state and highlights it with the reason | secondary |
| 7 | Solver visualiser: step/auto-play the solver's deductions on the board | **stretch** |
| 8 | Import/export: `.non` and JSON, share via URL hash | **stretch** |
| 9 | Image → puzzle: load a picture, threshold to a grid, make it unique | **stretch** |
| 10 | CLI: solve / generate / rate / ASCII render | **stretch** |

Required set (4): 1, 2, 4, 5 (rating #3 ships with the solver as part of 2).
