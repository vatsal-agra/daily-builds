# Kepler
Symbolic regression engine in Go — discovers closed-form equations from data.
**Status: Phase 4 done** (stretch features + polish). Tests/demo/final README follow in Phases 5–6.

Working so far: expression engine (parse / print / simplify / differentiate), genetic-programming
search with island model, Nelder-Mead constant fitting, Pareto front with holdout model selection,
HTML reports, and a CLI (`fit`, `bench`, `gen`, `eval`, `diff`, `datasets`).

```
go build -o kepler ./cmd/kepler
./kepler bench                      # rediscover 7 physics laws from sampled data
./kepler gen kinetic > k.csv && ./kepler fit -report r.html k.csv
```
See PLAN.md and REVIEW.md.
