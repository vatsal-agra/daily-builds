# Mortise
Incremental build system in Go (content hashes, early cutoff, depfile dynamic deps, parallel scheduler).

**Status: Phase 2 complete** — the four required features work end-to-end:
1. Mortisefile language (variables, functions, `%` pattern rules, grouped outputs, automatic variables)
2. Parallel scheduler (`-j`, `-k`, cycle detection, fail-fast cancellation)
3. Content-hash incremental builds with early cutoff and a persistent database
4. Dynamic dependencies from `@depfile` (gcc `-MMD` style)

Try it: `go build -o mortise ./cmd/mortise && cd examples/cproj && ../../mortise`

See PLAN.md for the roadmap. Full README arrives in Phase 6.
