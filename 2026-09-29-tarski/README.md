# Tarski
Datalog engine in Go (stdlib only). Status: Phase 2 done — 4 required features implemented
(parser, semi-naive evaluation, stratified negation + safety, built-ins/queries/provenance).
Aggregates, naive-vs-semi-naive bench and a REPL are already wired in (stretch, to be reviewed).
Build: `go build -o tarski . && ./tarski run examples/family.dl`. See PLAN.md.
