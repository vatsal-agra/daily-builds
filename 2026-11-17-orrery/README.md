# Orrery (in progress — Phase 3 complete)

N-body gravity laboratory in Go, standard library only. See [PLAN.md](PLAN.md) and [REVIEW.md](REVIEW.md).

Status: the 4 required features work end to end (integrator suite + diagnostics, Barnes–Hut tree, scenario DSL /
Kepler oracle / orbital elements, HTML report). The adversarial review found and fixed 14 issues (see REVIEW.md).

```
go build -o orrery ./cmd/orrery && ./orrery bench twobody -dt 0.01 -T 100
```
