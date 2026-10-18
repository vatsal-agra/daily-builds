# Mortise
Incremental build system in Go (content hashes, early cutoff, depfile dynamic deps, parallel scheduler, action cache).

**Status: Phase 5 complete (verified: `./demo.sh` 46/46, `go test -race -count=3` green)** — required features 1–4 plus all three stretch features:
5. content-addressed action cache · 6. `why` / `graph` / `-n` · 7. `watch`, `stats`, HTML build report + Chrome trace

Try it: `go build -o mortise ./cmd/mortise && cd examples/cproj && ../../mortise && ../../mortise why`

See PLAN.md (design), REVIEW.md (adversarial review). Full README arrives in Phase 6.
