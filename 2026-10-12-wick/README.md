# Wick — a from-scratch WebAssembly toolchain

Wick is a zero-dependency Rust implementation of the WebAssembly stack: a **text-format assembler**, a
**binary decoder and encoder**, a **validator** built on the spec's stack-polymorphic type-checking algorithm,
an **interpreter**, a **disassembler**, an **execution profiler** with an HTML report, and a
**differential fuzzer that checks the interpreter against V8** (Node's built-in WebAssembly engine).
It runs real clang output, and its answers match both native execution and V8.

~5k lines of Rust in `src/`, ~1.5k lines of tests, 0 crates.

## Run it

```bash
cargo build --release
./target/release/wick run examples/fib.wat --invoke fib 20            # i32:6765
./target/release/wick asm examples/fib.wat -o fib.wasm && ./target/release/wick dis fib.wasm
./target/release/wick run examples/programs.wasm --invoke nqueens 8 --html profile.html --trace 50
./verify.sh            # builds, runs every test, fuzzes against V8 (needs node for the V8 steps)
```

CLI: `asm`, `dis`, `validate`, `info`, `run` (`--invoke NAME ARGS…`, `--fuel N`, `--profile`, `--html FILE`,
`--trace N`, `--state`), `fuzz`, `mutants`, `check-batch`. Run `wick help` for details. The CLI provides
`env.print_i32/i64/f32/f64/char` host imports. Float args accept decimal, `inf`, `nan`, `bits:0xHEX`.

Library use: `wat::parse_module` → `validate::validate` → `Instance::new(module, Imports)` → `inst.invoke("f", &[Value::I32(3)])`.

## Features

| | Feature | Status |
|---|---|---|
| 1 | **WAT assembler** — flat and folded syntax, `$names`, inline import/export, hex/decimal/hex-float literals, string escapes, nested comments, positioned errors | shipped (required) |
| 2 | **Binary decoder + validator** — all sections incl. datacount, hostile-input hardened, spec type-checking with polymorphic stacks, precise errors | shipped (required) |
| 3 | **Interpreter** — every i32/i64/f32/f64 op (sat-trunc, sign-ext), control flow incl. multi-value and block/loop params, memory (+`copy`/`fill`/`grow`), tables + `call_indirect`, globals, host imports (func/global/memory/table), all spec traps, call-depth and stack limits | shipped (required) |
| 4 | **Differential fuzzer vs V8** — type-directed generator emitting valid, terminating, NaN-canonical programs; compares every return value, trap kind, final memory hash and every global | shipped (required) |
| 5 | **Disassembler** — binary → WAT that re-assembles to an identical module | shipped (stretch) |
| 6 | **Profiler + HTML report** — per-function and per-opcode counts, call-graph edges, call-depth timeline, instruction trace | shipped (stretch) |
| 7 | **Fuel metering** — deterministic instruction budget (`--fuel`) | shipped (stretch) |

Supported beyond MVP: sign-extension ops, saturating float→int, multi-value, `memory.copy/fill`, typed `select`.
Not supported (rejected with a specific message): reference types, SIMD, threads, exceptions, GC, multi-memory,
passive segments, `memory.init`, `table.*`, imported mutable globals. One memory / one table per module.

## How it was verified

| check | scale | result |
|---|---|---|
| Wick vs V8 on random programs (results, traps, memory, globals) | 2 000 per `verify.sh`; 4 000 + 3 000 + 300 during development | 0 disagreements (~100 k calls) |
| Validator vs V8 on corrupted modules (AST-level and byte-level mutants) | ~50 000 | 0 lax, 0 strict, 0 panics |
| Hand-written corpus (`tests/corpus`, 372 directives) | run on Wick **and** replayed on V8 | all agree |
| C workloads compiled by clang → wasm32 vs the same C compiled natively | 38 calls | identical (incl. bit-exact doubles) |
| encode/decode/disassemble/assemble round trips | 3 000 generated programs | identical |
| Oracle sanity: inject a bug, confirm the harness reports it | 2 bugs | both caught (see REVIEW.md) |
| Hostile inputs (4 GiB memory, deep nesting, runaway recursion, garbage) | 18 cases | clean errors only |

## Why I built this today

Nothing in this repo touched WebAssembly, and it is the rare "from scratch" target with an *independent,
free oracle*: V8 ships in Node, so correctness is measured rather than asserted. That let me spend the
effort on the part that usually gets skipped — finding out whether the tests can actually fail.

## Where a human could take this next

* Performance: pre-resolve branch targets and fuse common instruction pairs (currently ~7 M calls/s on `fib`).
* More proposals: reference types + `table.*`, bulk-memory `memory.init`/passive segments, SIMD, tail calls.
* A WASI layer so clang/rustc `wasm32-wasi` programs run unmodified.
* Component-model / multi-module linking (shared memories and tables between instances).
* Coverage-guided fuzzing and test-case minimisation for fuzz disagreements.
* A debugger front-end on top of the tracer (single-step, breakpoints, value-stack view).

See `PLAN.md` (design) and `REVIEW.md` (adversarial review and its 15 findings).
