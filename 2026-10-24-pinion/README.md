# Pinion

PubGrub-style dependency resolver in Ruby (no gems).

**Status: Phase 5 (verification) complete** — `./verify.sh` is green: 155 tests, differential fuzz, demo tour, browser check. [REVIEW.md](REVIEW.md) lists 16 findings, all fixed. Stretch features shipped: differential fuzzer, conservative update + lock diff, HTML graph, prerelease/yank policy.

Working end to end:

1. SemVer + constraint language + exact version-set algebra (`lib/pinion/version*.rb`, `constraint.rb`)
2. PubGrub solver with conflict learning and backjumping (`solver.rb`)
3. Human-readable failure explanations (`report.rb`)
4. Manifest / registry / lockfile + CLI (`bin/pinion resolve|lock|verify|tree|why|update|diff|range|gen|fuzz`)

Try: `cd examples/webapp && ../../bin/pinion resolve conflict.json`

See [PLAN.md](PLAN.md) for the design.
