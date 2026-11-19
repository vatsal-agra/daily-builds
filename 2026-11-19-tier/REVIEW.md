# REVIEW — adversarial pass on Tier (Phase 3)

Method: randomized invariant tests (no overlaps, minlen respected, ports on borders, canvas bounds, determinism,
BIT crossing counter vs brute force, heuristic vs exact oracle), network simplex vs brute-force optimum,
performance probes on 300–1000-node graphs, then hostile hand-written inputs through the CLI.

What held up: network simplex matched brute-force optimum on 400/400 random graphs; invariants held on 1,200 random
layouts (4 option sets); layouts are deterministic; 800-node cyclic graph lays out in 0.16 s; the parser rejected every
malformed DOT probe with a positioned error. Everything below is what *didn't* hold up.

| # | Severity | Finding | Reproduction | Status |
|---|----------|---------|--------------|--------|
| R1 | High (UX) | Disconnected components are laid in ONE row — 150 isolated nodes → 14,426 px wide, 40 small components → 6,428 px wide | `digraph{n0;…n149;}` → `tier metrics` | FIXED — shelf packing into rows targeting a ~1.5:1 canvas |
| R2 | Medium | Several self-loops on one node are drawn on top of each other (identical Bézier), so `a->a; a->a` looks like one loop | `digraph{a->a;a->a;a->a}` | FIXED — k-th loop is nested with growing radius |
| R3 | Medium | Absurd `width`/`height` attributes accepted (`width=1e9` → billion-pixel SVG) | `digraph{a [width=1e9]}` | FIXED — sizes above 4000 pt are rejected with a clear error |
| R4 | Medium | Layer heights were computed per component, so rank *r* sat at different y in different components; rank bands were therefore wrong | two components of different node heights, `-bands` | FIXED — layer geometry is global across components |
| R5 | Low (lazy code) | Rank-band renderer looped to `len(bands)+1000` with a magic cutoff and drew bands across multi-row packings where they are meaningless | read `render/svg.go` | FIXED — bands iterate real ranks and are only drawn when the drawing is a single row (`Result.Rows == 1`) |
| R6 | Low (lazy code) | `hasLoopNode` scans every loop for every port (O(N·L)); a `pr.g.Nodes[..].ID != ""` guard silently skipped loop-padding removal for nodes with an empty id | `digraph{"" -> ""; "" -> x}` ports drift | FIXED — per-node loop counts precomputed, hack removed |
| R7 | Low | Errors from stdin were prefixed `-:` | `echo 'x' \| tier metrics -` | FIXED — `<stdin>` |
| R8 | Low | `\N` escape (node name) in labels unsupported; shows literally | `a [label="id: \N"]` | FIXED |
| R9 | High (UX) | Edge labels were drawn at a path midpoint with nothing reserving room: labels overlapped each other and neighbouring edges (see `connect`/`timeout` in the TCP example) | `examples/states.dot` | FIXED — labelled edges get a label-sized virtual node in the layering (ranks are doubled, as Graphviz does), so crossing minimisation and Brandes–Köpf keep room for the text; loop labels widen the node's padding |
| R10 | Low | `tier gen -kind tree` used an obscure parent formula | read `gen/gen.go` | FIXED — plain random-recursive-tree parent |
| R11 | Low | Report page showed 5 variants even for a single node / tiny graphs, with the "full pipeline" card not distinguishable when all strategies tie | `digraph{a}` report | FIXED — card titles show "identical to full pipeline" when metrics tie |

Re-run criterion: every reproduction above must now behave correctly, and the property/oracle tests plus new
regression tests for R1–R4, R7–R9 must pass (see `layout/regress_test.go`, `cmd/tier/cli_test.go`).
