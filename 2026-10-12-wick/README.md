# Wick
A from-scratch **WebAssembly toolchain in Rust** (zero dependencies): WAT assembler, binary decoder, spec-algorithm validator, interpreter, disassembler, profiler — differentially fuzzed against V8.

**Status after phase 2 (core build):**
- [x] WAT assembler (flat + folded syntax) → `.wasm`
- [x] Binary decoder + validator
- [x] Interpreter (all MVP numerics, control flow, memory, tables, globals, host imports, multi-value, traps)
- [x] Differential fuzzer: 4000 random programs / 66k calls agree with V8 (`wick fuzz` + `node diff/diff.js`)

Quick try: `cargo build --release && ./target/release/wick run examples/fib.wat --invoke fib 20`

**Phase 3 (adversarial review) done** — 15 findings fixed, see REVIEW.md. Added: conformance corpus replayed on V8,
validator mutation-differential (31k mutants, 0 disagreements), hostile-input battery, clang-vs-native end-to-end test.

**Phase 4 done** — stretch features shipped: disassembler (round-trip verified), profiler + HTML report, fuel metering. Report polished (readable share column, named call targets in trace).

Full README comes in the ship phase. See PLAN.md.
