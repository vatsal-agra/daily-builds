# Wayfinder — PLAN

## Concept
**Wayfinder** is a from-scratch pathfinding laboratory in Go (stdlib only). It implements the
algorithm families that every game, robot and logistics system leans on — uninformed and heuristic
search, Jump Point Search, any-angle planning, and *incremental* replanning (D* Lite) for worlds
that change while you walk through them — and then lets you **watch** them think via a
self-contained HTML replay viewer, and **prove** them against each other with a randomized
cross-validation fuzzer.

Nothing in this repo so far covers graph search / motion planning (the ledger has SAT, SQL, SLAM,
physics, DHTs, compilers... but no pathfinding at all), so this fills a real gap.

## Why it is interesting
* JPS is famously easy to get subtly wrong. We pair it with a fuzzer that compares its optimal
  cost against A* and Dijkstra on thousands of random maps — correctness is *measured*, not asserted.
* D* Lite is the algorithm that drove real Mars-rover/DARPA-era robot navigation: a robot with a
  limited sensor discovers walls as it walks and repairs its plan with a tiny fraction of the work
  of re-planning from scratch. We quantify exactly that saving.
* Any-angle (Theta*) paths show the gap between grid-optimal and truly-shortest paths.
* The viewer makes the difference between "expanded 14,000 nodes" and "expanded 300" visceral.

## Movement model (shared by every algorithm)
8-connected grid. Cell cost 1..9 (terrain), 0 = wall. Step cost = length × (cost(from)+cost(to))/2
(length 1 orthogonal, √2 diagonal). A diagonal step is legal only if **both** orthogonal
neighbours are open (no corner cutting, no squeezing). Octile heuristic scaled by the minimum
open-cell cost on the map keeps A* admissible and consistent.

## Architecture
```
grid/   Grid type, ASCII map format (parse/format), terrain legend, seeded generators
        (random, maze, rooms, caves), legal-move + step-cost rules, line-of-sight
plan/   heap.go (indexed binary heap) · astar.go (Dijkstra + A*, trace) · jps.go
        theta.go (Theta*) · dstar.go (D* Lite) · hpa.go (HPA*, stretch) · validate.go
viz/    Self-contained HTML replay viewer generator (canvas + embedded JSON)
cmd/wayfinder/  CLI: gen, solve, compare, explore (D* Lite sim), bench, fuzz, html
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Map format + terrain costs + seeded generators (random, maze, rooms, caves) with guaranteed-solvable start/goal | **required** |
| 2 | Optimal planners: Dijkstra, A*, Jump Point Search — with full expansion traces, all cross-checked for equal cost | **required** |
| 3 | D* Lite incremental replanning: agent with sensor radius walks an initially unknown map; work compared with from-scratch A* replans | **required** |
| 4 | Self-contained HTML replay viewer (scrubbable expansion animation per algorithm, D* Lite walkthrough) | **required** |
| 5 | Theta* any-angle planning with exact line-of-sight and path-length comparison | secondary |
| 6 | Benchmark suite (expansions / time / cost across map families) and CLI `fuzz` cross-validator | secondary |
| 7 | HPA* hierarchical planner (clusters, entrances, abstract graph, path refinement) | stretch |
| 8 | Path smoothing post-processor / flow-field | stretch |

## Definition of done
Every feature exercised by `go test ./...` and `demo.sh`; REVIEW.md lists attacks and fixes.
