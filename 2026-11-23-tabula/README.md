# Tabula
School timetabling solver in Go: constraint search finds a feasible week, simulated annealing polishes it.

**Status: Phase 2 — core build done.** Required features working end-to-end: problem model + validation,
MRV/forward-checking constructor, annealing optimiser with itemised cost, impossibility diagnostics.
Also already in: HTML viewer, independent verifier, generator, re-solve, ICS (to be hardened in later phases).
See PLAN.md. Try: `go build -o tabula ./cmd/tabula && ./tabula solve examples/school.json -html out.html`
