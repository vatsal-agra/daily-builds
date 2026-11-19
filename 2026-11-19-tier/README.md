# Tier
Layered (Sugiyama) graph-drawing engine in Go — DOT in, SVG/HTML out.

**Status: Phase 2 — core build done.** Required features implemented and exercised:
1. DOT-subset parser with positioned errors (`dot/`)
2. Cycle removal: Eades–Lin–Smyth greedy FAS + DFS baseline (`layout/acyclic.go`)
3. Network-simplex optimal layering, verified against brute force (`layout/rank.go`)
4. Median/transpose crossing minimisation + Brandes–Köpf coordinates + SVG (`layout/order.go`, `coord.go`, `render/`)

Try: `go run ./cmd/tier layout examples/build.dot -o build.svg`

(Full README arrives in Phase 6. See PLAN.md.)
