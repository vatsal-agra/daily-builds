# Kepler
Symbolic regression engine in Go — discovers closed-form equations from data.

**Status: Phase 2 done** (core build). Required features working end-to-end:
expression engine (parse/print/simplify/diff), genetic-programming search,
Nelder-Mead constant fitting, Pareto front + CLI (`fit`, `bench`, `gen`, `eval`, `diff`).

```
go build -o kepler ./cmd/kepler
./kepler bench            # rediscover 7 physics laws from sampled data
./kepler gen kinetic > k.csv && ./kepler fit k.csv
```
See PLAN.md. Full README arrives in Phase 6.
