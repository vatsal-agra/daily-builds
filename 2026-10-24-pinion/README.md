# Pinion

PubGrub-style dependency resolver in Ruby (no gems).

**Status: Phase 3 (adversarial review) complete** — see [REVIEW.md](REVIEW.md) for 12 findings, all fixed.

Working end to end:

1. SemVer + constraint language + exact version-set algebra (`lib/pinion/version*.rb`, `constraint.rb`)
2. PubGrub solver with conflict learning and backjumping (`solver.rb`)
3. Human-readable failure explanations (`report.rb`)
4. Manifest / registry / lockfile + CLI (`bin/pinion resolve|lock|verify|tree|why|update|diff|range|gen|fuzz`)

Try: `cd examples/webapp && ../../bin/pinion resolve conflict.json`

See [PLAN.md](PLAN.md) for the design.
