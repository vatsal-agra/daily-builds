# Tier

A from-scratch **layered (Sugiyama) graph-drawing engine** in Go. Feed it a graph in a practical DOT subset; it
returns a hierarchical drawing as SVG (or JSON, or a self-contained HTML comparison report). Every stage is
implemented here — no Graphviz, standard library only.

```
DOT --parse--> graph --cycle removal--> DAG --network simplex--> ranks --virtual nodes--> proper layered graph
    --median sweeps + transpose--> vertex order --Brandes–Köpf--> x --ports + splines--> SVG / HTML / JSON
```

Samples are in `gallery/` (open `gallery/report-build.html` in a browser).

## Run it

```
go build -o tier ./cmd/tier
./tier layout  examples/compiler.dot -bands -o compiler.svg     # draw
./tier layout  examples/states.dot  -rankdir LR -o tcp.svg       # left-to-right
./tier metrics examples/build.dot                                # crossings, edge length, bends…
./tier report  examples/build.dot -o report.html                 # 5 strategies side by side
./tier exact   small.dot                                         # heuristic vs optimal crossings
./tier gen -kind layered -n 60 -seed 3 | ./tier layout - -o g.svg
./verify.sh                                                      # everything, ends ALL GREEN
```
Flags (`-h` per command): `-rankdir TB|LR`, `-ranker simplex|longest`, `-acyclic greedy|dfs`,
`-order sweep|none`, `-coord bk|packed`, `-nodesep`, `-ranksep`, `-polyline`, `-bands`, `-format svg|json`.
Flags may come before or after the file; `-` reads stdin.

DOT subset: `digraph`/`graph`/`strict`, node & edge statements, `->` chains, `node/edge/graph [..]` defaults,
`rankdir`, `nodesep`, `ranksep` (points), node `label` (`\n`, `\N`), `shape` (box, ellipse), `width`, `height`,
edge `label`, `weight`, `minlen`. Subgraphs, ports and HTML labels are rejected with positioned errors.

## Features

Required
1. **DOT parser** with line/column errors, defaults, strict mode, three comment styles.
2. **Cycle removal** — Eades–Lin–Smyth greedy feedback-arc set (+ DFS baseline); reversed edges drawn dashed/orange; self-loops, multi-edges.
3. **Network-simplex layering** (feasible tight tree, cut values, enter/leave pivots, balancing) with `weight`/`minlen`; verified optimal against brute force on 400 random graphs.
4. **Crossing minimisation + Brandes–Köpf** — weighted-median sweeps, transpose, BIT crossing counter; four-way BK alignment with type-1 conflict marking; SVG output.

Stretch (all shipped)
5. Spline routing through virtual-node chains with border ports spread by neighbour order (ellipse-aware), arrowheads, nested self-loops.
6. Edge labels laid out as label-sized virtual nodes, so text gets reserved room (ranks doubled as in Graphviz).
7. LR orientation, text-sized boxes/ellipses, components shelf-packed into rows, global rank alignment, rank bands.
8. HTML report comparing the full pipeline with longest-path layering / no ordering / packed x / DFS cycle removal, with hover highlighting.
9. Exact-crossings oracle (DP over layer permutations) to measure the heuristic's gap — mean gap 0.24 crossings on 139 small random graphs.

Verification: `verify.sh` runs 30 checks (gofmt, vet, `go test -race` — 26 test functions incl. simplex vs brute force,
random invariants, BIT counter vs brute force, heuristic-vs-oracle — plus CLI end-to-end). REVIEW.md lists the 11 issues
the adversarial pass found and fixed.

## Why I built this today
Nothing in the ledger draws graphs, and the pipeline is a rare case where every stage has a classical algorithm *and*
a measurable objective, so correctness can be checked by oracles instead of by eye. Network simplex in particular is
famously fiddly; getting it provably optimal was the fun part.

## Where a human could take this next
- Subgraph/cluster support (compound nodes) and DOT ports; edge-label placement beside rather than on the line.
- Orthogonal edge routing; edge bundling for dense graphs.
- Incremental/stable layout for animated graph edits; better crossing minimisation (e.g. sifting, ILP for small layers).
- Faster network simplex (incremental cut-value updates instead of per-pivot recomputation) for 10k+ node graphs.
- A browser front-end with live editing — the engine is pure Go and would compile to WASM.
