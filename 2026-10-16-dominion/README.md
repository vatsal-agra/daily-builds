# Dominion

An optimizing compiler middle- and back-end built from scratch in Go: **Dom source → SSA IR → optimizer → register allocator → VM**.

**Status: Phase 3 (adversarial review) complete — see REVIEW.md** — the four required features work end to end:

1. Front-end + SSA IR toolchain (lexer/parser/lowering, IR printer+parser, verifier, reference interpreter)
2. SSA construction (dominators, dominance frontiers, mem2reg) + CFG simplification
3. Optimizer (SCCP, instcombine, GVN, memopt, LICM, inlining, tail-recursion elimination, DCE)
4. Backend (critical-edge splitting, phi→parallel copies, liveness, linear scan with spilling, ABI, VM)

See [PLAN.md](PLAN.md). Quick try: `go run ./cmd/dom bench examples/*.dom`.

Also available already: `dom fuzz` (differential fuzzer: generated programs, mutated IR, random pass orders, 3 register
files) and `scripts/recheck.sh` (re-runs every REVIEW.md reproduction).
