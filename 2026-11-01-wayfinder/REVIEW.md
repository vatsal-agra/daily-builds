# REVIEW — adversarial pass (Phase 3)

Method: wrote hostile tests (`grid/grid_test.go`, `plan/edge_test.go`, fuzzers in `plan/plan_test.go`),
drove the CLI with bad input, and loaded the viewer in headless Chromium. Every item below was
either found by an attack or by reading the code as a hostile reviewer; all are fixed and covered
by a test that fails without the fix.

| # | Finding | How found | Fix |
|---|---------|-----------|-----|
| 1 | **JPS returned "no path" in 1-wide corridors.** Under the no-corner-cutting rule, an orthogonal turn is a *forced neighbour* when the cell diagonally behind it is a wall; the textbook rule (which assumes corner cutting) misses it. | `TestFuzzOptimalAgreement` on mazes (seed 1) | Re-derived forced neighbours for this movement rule; JPS now agrees with A*/Dijkstra on 1,500 fuzzed maps + 200 uniform-terrain maps. |
| 2 | **Agent stepped onto cells it had never sensed** — with radius 1 (Euclidean) diagonal neighbours are at distance √2, so a diagonal move was planned through unseen walls. | `TestExploreMatchesAStar` ("planner chose illegal move") | Sensor always perceives the 8 adjacent cells in addition to the radius. |
| 3 | **D\* Lite silently returned costs lower than optimal** (e.g. 37.63 vs true 39.97). Keys that are mathematically equal differed in the last float bits, so (a) the heap ordered by k1 noise instead of k2 and (b) the termination test `top < key(start)` stopped too early, leaving stale low `g` values. | Cross-check against A* in `Explore`; then isolated with a replica + per-cell Dijkstra oracle | Tolerant key comparison (1e-9) in the heap and termination test, tolerant `g == rhs` test (`eq`, also handles Inf). |
| 4 | **`explore -radius 1000000` hung** (O(r²) scan loop per step, not clipped to the map). | `TestHugeRadiusIsFast` | Loop bounds clipped to the map; radius capped at W+H. |
| 5 | **Map round-trip lost terrain under S/G** (`Format` prints `S`, `Parse` reads cost 1) so a generated map and its saved file were different worlds. | `TestParseFormatRoundTrip` | Generator forces S/G cells to cost 1. |
| 6 | **Viewer re-painted every expansion every frame** and re-filled the whole terrain every frame — the 800×800 case crawled. | Reading the viewer code | Terrain cached on an offscreen canvas; expansions painted incrementally (full repaint only when scrubbing backwards). |
| 7 | **`html` on a huge map produced a 6.5 MB page** (900×900 open map). | CLI stress | Refuses > 640,000 cells with an explanatory error. |
| 8 | Line-of-sight was untested and hand-rolled — the riskiest geometry code. | Hostile review | Cross-checked against an independent exact-rational reference (Liang–Barsky + lattice-vertex rule) on 24,000 random segment queries, incl. symmetry. Passed first time; test kept. |
| 9 | Unknown command / missing flags / bad files / invalid generator params / unreachable goals / start==goal / wall start | CLI + unit tests | All exit non-zero with a one-line message (exit 3 for "no path"); start==goal returns cost 0. |
| 10 | Leaked ghost walls: the explore view faintly drew undiscovered walls, contradicting the "unknown" legend. | Visual review | Legend now says so honestly (ghost shading = ground truth not yet perceived). |
| 11 | **A\* was ~40× slower than Dijkstra** on big maps despite 5× fewer expansions: the heuristic called `Grid.MinCost()` (a full-grid scan) on every evaluation. Found when the Phase-4 benchmark printed A\* at 298 ms vs Dijkstra at 7 ms. | `wayfinder bench` | Heuristic scale computed once per search (all planners, HPA graph stores it). A\* now 1.9 ms on the same maps. |

## Known limitations (documented, not bugs)
* JPS only runs on uniform-cost maps (pruning relies on path symmetry) — it refuses mixed terrain with a clear error.
* The D* Lite initial plan is a full backward search (no heuristic advantage), so the *first* replan of every run costs more than A*; the saving is in the repairs. The viewer shows this honestly.
* Heap key comparison uses an absolute 1e-9 tolerance; fine for map costs ≤ 9 × 4096² but not for arbitrary float weights.

## Re-run gate
`go test ./...` green after fixes; CLI sweep above reproduced with all errors clean.
