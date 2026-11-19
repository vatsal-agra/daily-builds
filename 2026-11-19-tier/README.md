# Tier
Layered (Sugiyama) graph-drawing engine in Go — DOT in, SVG/HTML out.

**Status: Phase 4 — stretch features and polish done.** Shipped so far: DOT parser, cycle removal, network-simplex
layering, crossing minimisation, Brandes–Köpf coordinates, spline routing with ports, edge-label nodes, self-loops,
LR orientation, component packing, HTML strategy report, exact-crossings oracle. Try:
`go run ./cmd/tier layout examples/compiler.dot -bands -o compiler.svg`. Full README in Phase 6.
