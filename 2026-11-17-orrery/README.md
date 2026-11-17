# Orrery (in progress — Phase 4 complete)

N-body gravity laboratory in Go, standard library only. See [PLAN.md](PLAN.md) and [REVIEW.md](REVIEW.md).

Shipped so far: the 4 required features (integrator suite + diagnostics, Barnes–Hut tree, scenario DSL / Kepler oracle /
orbital elements, HTML report) and 4 stretch features (empirical convergence order, time-reversibility test,
Benettin Lyapunov estimator, Wisdom–Holman integrator). Review found and fixed 16 issues.

```
go build -o orrery ./cmd/orrery
./orrery bench twobody -dt 0.01 -T 100
./orrery order
./orrery reverse figure8 -dt 0.01 -T 6
./orrery lyap plummer -n 16 -m yoshida4 -dt 0.005 -T 40
```
