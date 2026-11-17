# Orrery (in progress — Phase 2 complete)

N-body gravity laboratory in Go, standard library only. See [PLAN.md](PLAN.md).

Status after Phase 2 (core build) — the 4 required features work end to end:

1. **Integrator suite** — euler, symeuler, leapfrog, yoshida4, rk4, adaptive dopri5, plus a Wisdom–Holman Kepler-drift map; conserved-quantity diagnostics (`orrery run`, `orrery bench`).
2. **Barnes–Hut octree** with exact-sum validation (`orrery bh`).
3. **Scenario DSL + generators + Kepler oracle & orbital elements** (`orrery gen`, `orrery elements`).
4. **HTML viewer/report** (`orrery report … -o out.html`).

```
go build -o orrery ./cmd/orrery && ./orrery bench twobody -dt 0.01 -T 100
```
