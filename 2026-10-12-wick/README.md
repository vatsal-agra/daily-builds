# Wick
A from-scratch **WebAssembly toolchain in Rust** (zero dependencies): WAT assembler, binary decoder, spec-algorithm validator, interpreter, disassembler, profiler — differentially fuzzed against V8.

**Status after phase 2 (core build):**
- [x] WAT assembler (flat + folded syntax) → `.wasm`
- [x] Binary decoder + validator
- [x] Interpreter (all MVP numerics, control flow, memory, tables, globals, host imports, multi-value, traps)
- [x] Differential fuzzer: 4000 random programs / 66k calls agree with V8 (`wick fuzz` + `node diff/diff.js`)

Quick try: `cargo build --release && ./target/release/wick run examples/fib.wat --invoke fib 20`

Full README comes in the ship phase. See PLAN.md.
