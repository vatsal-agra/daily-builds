# Silicon

A from-scratch cycle-accurate 5-stage pipelined RISC-V (RV32I subset)
CPU simulator, in pure Python.

**Status: Phase 1 (plan) complete.** See `PLAN.md` for the full design.
Implementation in progress — this README will be filled in with usage
instructions, the full feature list, and results as each phase lands.

## Status

**Phase 2 (core build) complete.** All 4 required features implemented and
cross-verified: the RV32I assembler/encoder, the sequential golden-model
simulator, the cycle-accurate 5-stage pipeline (hazard detection +
forwarding + load-use stalling), and branch prediction (static vs dynamic,
with a measured misprediction-rate difference). 5 example programs
(fibonacci, gcd, sumarray, bubblesort, matmul) all produce pipeline output
that exactly matches the sequential golden model's final register file and
memory image, across 7 different predictor/cache/latency configurations
each (35/35 combinations verified with zero mismatches).

**Phase 3 (adversarial review) complete.** 5 real bugs found and fixed
(3 pipeline-timing correctness bugs, 2 assembler/encoding bugs) — see
`REVIEW.md` for full root-cause writeups. A 99-test automated suite
(`tests/`) now guards every one of them plus broad ISA/assembler/cache/
functional-simulator coverage; all 99 tests pass.
