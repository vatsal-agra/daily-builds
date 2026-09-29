# Tarski
Datalog engine in Go (stdlib only). Status: Phase 3 done (see REVIEW.md) — core engine reviewed and hardened
via differential fuzzing against an independent oracle. Stretch features (aggregates, naive/bench, REPL) present and being polished.
Build: `go build -o tarski . && ./tarski run examples/family.dl`. See PLAN.md.
