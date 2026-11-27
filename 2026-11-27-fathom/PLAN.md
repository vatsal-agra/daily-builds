# Fathom — Plan

## Concept
Minesweeper is a puzzle of *incomplete information*. Fathom is a Minesweeper
engine whose centrepiece is an **exact probabilistic solver**: for any board
position it computes the true probability that every hidden cell is a mine —
not a heuristic, but the exact count over all consistent mine placements,
including the global mine-count constraint and the unconstrained "interior" cells.
On top of it: a **no-guess board generator**, a **luck analyzer** that grades every move you
made against the truth, a **solver benchmark**, and a polished playable web UI
with a live probability heat-map.

## Why it's interesting
- Exact inference is a real algorithms problem: constraint components, backtracking
  enumeration, convolution of per-component mine-count distributions, and
  binomial weighting of the unconstrained region (BigInt arithmetic, no float drift).
- The solver is used three ways (hint, generator verification, benchmark), which keeps it honest.
- "Was that death bad luck or a bad move?" becomes a computable number.

## Architecture (zero dependencies, ES modules, Node 22 + browser)
```
src/rng.js        seeded PRNG (mulberry32) + string seed hashing
src/board.js      game engine: layout, first-click-safe, reveal/flood, chord, flags, win/loss
src/solver.js     exact probability engine + best-move selection
src/generator.js  seeded board generation, no-guess verification via solver self-play
src/analysis.js   luck analyzer: per-move survival probability, guess detection
src/bench.js      solver self-play benchmark (win-rate per difficulty)
src/cli.js        terminal play / solve / generate / bench
web/              index.html + app.js + style.css (heat-map UI)
build.js          bundles everything into dist/fathom.html (single standalone file)
serve.js          tiny static server for dev
test/             node:test suite + demo.sh
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Game engine: first-click-safe seeded layouts, flood reveal, chording, flags, win/loss | **required** |
| 2 | Exact probability solver (components + backtracking + convolution + global mine count) | **required** |
| 3 | No-guess board generator: boards verified solvable by certain deduction alone | **required** |
| 4 | Web UI: playable, probability heat-map overlay, hint, solver step/auto-play | **required** |
| 5 | Luck analyzer: per-move survival odds, guess count, cumulative luck report | stretch |
| 6 | Solver benchmark CLI: win-rate / guess-rate across difficulties and seeds | stretch |
| 7 | Single-file bundle `dist/fathom.html` + shareable seed URLs | stretch |
| 8 | Terminal CLI: play, solve a pasted board, generate | stretch |

## Definition of done
All 4 required features end-to-end; adversarial REVIEW.md with fixes; ≥1 stretch (aiming for 4);
tests + demo script green; README + LEDGER.
