# Shove — PLAN

## Concept
A complete Sokoban toolkit in Go (stdlib only): parse levels, **solve them optimally in pushes**, **generate new
solvable levels by playing the game backwards**, **verify any move string**, and **export a polished single-file HTML
game** whose levels ship with machine-verified solutions.

## Why it's interesting
Sokoban is PSPACE-complete; the solver needs real search engineering (A*, admissible assignment heuristic, dead-square
and freeze-deadlock pruning, player-region canonicalisation). The generator is the neat part: instead of generate-and-test
(almost all random layouts are unsolvable), it starts from a *solved* position and executes random legal **pulls**,
so every output is solvable by construction; the solver then rates it and keeps the hardest.

## Architecture
```
sok/level.go    XSB parse/format/validate, Level + State types
sok/moves.go    LURD move simulation + verifier (Replay)
sok/deadlock.go dead squares (reverse BFS), freeze deadlocks
sok/solver.go   A* over (box set, canonical player region), Hungarian lower bound
sok/gen.go      reverse-play generator, seeded RNG, difficulty rating
sok/html.go     single-file HTML game export (levels + verified solutions embedded)
cmd/shove       CLI: solve | gen | check | replay | html | bench
levels/         hand-authored packs (XSB)
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | XSB level parser/validator with precise errors (+ pretty printer) | **required** |
| 2 | Push-optimal A* solver: Hungarian-matching heuristic, dead squares, freeze deadlocks, region canonicalisation, node/time budget | **required** |
| 3 | Reverse-play level generator (solvable by construction), seeded, rated by solver, hardest-of-N | **required** |
| 4 | Playable single-file HTML game: canvas UI, undo/restart, live deadlock warning, solution playback of verified solutions, level select | **required** |
| 5 | Independent move-string verifier + terminal ASCII replay | stretch |
| 6 | Bench/report mode over a pack (nodes, pushes, time table, markdown) | stretch |
| 7 | Pack builder: generate pack of N levels sorted by measured difficulty | stretch |

(The verifier is also used internally to check every solver output, so 5 is cheap but is shipped as a user feature.)

## Definition of done
Every feature exercised by `go test ./...` plus `demo.sh`; solver output always re-verified by the independent replay.
