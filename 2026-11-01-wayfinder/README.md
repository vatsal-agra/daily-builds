# Wayfinder

A from-scratch **pathfinding laboratory** in Go (standard library only): Dijkstra, A\*, Jump Point Search,
Theta\* (any-angle), D\* Lite (incremental replanning in an unknown world) and HPA\* (hierarchical) — plus a
self-contained **HTML replay viewer** that lets you scrub through what each algorithm expanded, and a
**randomized cross-validator** that proves the planners agree with each other.

Open `examples/rooms-replay.html` in a browser for a sample replay — it is a single file, no server needed.

## Run it
```bash
go build -o wf ./cmd/wayfinder          # Go 1.24, no dependencies
./wf gen -kind caves -w 70 -h 40 -seed 5 -terrain 0.25 -o map.txt
./wf compare -map map.txt               # every applicable planner, one line each
./wf solve   -map map.txt -algo astar -draw
./wf explore -map map.txt -radius 3 -draw    # D* Lite agent, unknown world
./wf html    -map map.txt -o replay.html     # open in a browser
./wf fuzz -n 500                        # cross-validate everything on random maps
./wf bench -size 150 -seeds 5           # benchmark per map family
./demo.sh                               # exercises every feature end-to-end
go test ./...                           # unit, fuzz, CLI and viewer tests
```
Map files are ASCII: `#` wall, `.` open, `, ; ~ % &` terrain (cost 2, 3, 5, 7, 9), digits `1-9` explicit costs,
`S` start, `G` goal (`//` comment lines allowed; maps can be piped on stdin with `-map -`).

## Features
| # | Feature | Where |
|---|---------|-------|
| 1 | **Maps**: ASCII format, weighted terrain, seeded generators (random / maze / rooms / caves / open) with guaranteed-solvable endpoints | `grid/` · `wf gen` |
| 2 | **Dijkstra, A\*, JPS** with full expansion traces; JPS re-derived for a *no-corner-cutting* rule; all three produce identical costs on thousands of fuzzed maps | `plan/astar.go`, `jps.go` |
| 3 | **D\* Lite**: an agent with a sensor radius walks an initially unknown world; every replan is cross-checked against from-scratch A\* (the run errors out on any disagreement) | `plan/dstar.go`, `explore.go` · `wf explore` |
| 4 | **HTML replay viewer**: scrubbable/animated expansion order per algorithm, D\* Lite walkthrough with per-replan work table | `viz/` · `wf html` |
| 5 | **Theta\***: any-angle paths with exact integer line-of-sight (verified against an exact-rational reference) | `plan/theta.go`, `grid.LineOfSight` |
| 6 | **Benchmark + fuzz CLI**: expansions / time / cost-vs-optimal per map family; fuzzer cross-validates all planners | `wf bench`, `wf fuzz` |
| 7 | **HPA\*** (stretch): cluster entrances, abstract graph, intra-cluster paths, query-time start/goal insertion with rollback, path refinement | `plan/hpa.go` |

Shared movement model: 8-connected, step cost = length × mean of the two cell costs, a diagonal step needs **both**
orthogonal neighbours open (no corner cutting).

## What the numbers say (from `wf bench -size 150`)
* A\* expands ~100× fewer nodes than Dijkstra on open maps; **JPS expands 10–40× fewer than A\*** on rooms/caves.
* **Theta\*** paths are 3–6 % shorter than the best 8-connected path.
* **HPA\*** is 3–8 % longer than optimal, and its queries are the cheapest on large maps.
* **D\* Lite** needs 2–9× less work than re-running A\* in mazes and room maps, but is roughly *even* on sparse random
  terrain, where A\* is already cheap (the CLI says "MORE work" when it loses). See `REVIEW.md`.

## Why I built this today
The ledger had SAT solvers, databases, compilers, physics, DHTs and SLAM — but no classic graph-search /
path-planning build. Pathfinding is also a domain where correctness is subtle (JPS and D\* Lite are both famous for
off-by-one-neighbour and tie-breaking bugs — I hit both, see `REVIEW.md`), which makes a fuzz-validated implementation
a satisfying thing to build, and the viewer makes the algorithms *visible*.

## Verification
`go test ./...` covers: 1,500-map Dijkstra/A\*/JPS agreement, Theta\* validity, HPA\* connectivity/optimality bounds and
graph-reuse hygiene, D\* Lite vs A\* on 300 explorations, line-of-sight vs an exact reference (24,000 queries), parser /
generator edge cases, heap properties, viewer data integrity, and the CLI end-to-end. `tools/verify_viewer.js` loads the
viewer in headless Chromium and fails on errors or a blank canvas.

## Layout
```
grid/  map model, parser, generators, line of sight      plan/  heap, astar, jps, theta, dstar, explore, hpa
viz/   HTML viewer generator + template                  cmd/wayfinder/  CLI (+ fuzz, bench)
PLAN.md  REVIEW.md  demo.sh  examples/  tools/
```

## Where a human could take this next
* **Weighted any-angle**: Theta\* currently needs uniform terrain; field D\* / Anya would give optimal any-angle on weighted maps.
* **Optimal JPS on weighted grids** (JPS+ / jump-point with terrain "cost zones") and **bidirectional** or **ALT/landmark** heuristics.
* **Dynamic obstacles** (moving agents, time-expanded A\*/SIPP) and **multi-agent** planning (CBS, flow fields).
* **HPA\* upgrades**: multi-level hierarchy, incremental graph repair when the map changes, path smoothing.
* **3D / navmesh** back-end: replace the grid with a polygon navmesh and funnel algorithm.
* Make the viewer editable (draw walls, drag start/goal) by compiling the planners to WebAssembly.
