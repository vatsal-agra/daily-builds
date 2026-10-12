# Wick — PLAN

## Concept
**Wick** is a from-scratch WebAssembly (MVP + sign-ext + sat-trunc + multi-value) toolchain in Rust with zero
dependencies: a WAT text assembler, binary decoder, spec-algorithm validator, interpreter and disassembler, plus a
**differential fuzzer that checks the interpreter against V8** (Node's built-in WebAssembly engine) on thousands of
randomly generated programs.

## Why it's interesting
No prior build in this repo touches WebAssembly. It is a real, specified target (so "correct" is checkable, not
vibes): the validator is the spec's stack-polymorphic type-checking algorithm, numerics need exact IEEE-754 /
trapping semantics (NaN canonicalisation, `nearest`, saturating truncation, `i32.rem_s` overflow), and Node gives a
free oracle to differentially test against — the strongest verification available offline.

## Architecture
```
 src/
  leb.rs       LEB128 read/write
  ast.rs       Module, FuncType, Instr (structured), ValType
  wat.rs       lexer + s-expression parser + name resolution -> Module (flat and folded forms)
  encode.rs    Module -> .wasm bytes
  decode.rs    .wasm bytes -> Module (bounds-checked, errors with byte offsets)
  validate.rs  spec validation algorithm (operand/control stacks, polymorphic stack after unreachable)
  interp.rs    instantiate + execute (precompiled jump table, value stack, call frames, fuel, traps)
  num.rs       exact numeric ops (float min/max/nearest/trunc, sat, rotates, etc.)
  disasm.rs    Module -> WAT text (round-trips through the assembler)
  trace.rs     instruction trace / profile + HTML report
  fuzz.rs      random valid module generator (type-directed)
  main.rs      CLI: asm | dis | validate | run | fuzz-gen | trace
 tests/        integration tests (Rust) ; diff/  Node harness for differential testing
```

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | **WAT assembler** (flat + folded syntax, `$names`, inline exports/imports, data/elem, `br_table`, blocks with types) → valid `.wasm`, accepted by V8 | **required** |
| 2 | **Binary decoder + validator** (all sections, LEB bounds, spec stack-polymorphic type checking, precise errors) | **required** |
| 3 | **Interpreter** (all i32/i64/f32/f64 numerics, control flow, memory, tables, `call_indirect`, globals, imports/host funcs, traps, multi-value) | **required** |
| 4 | **Differential fuzzer vs V8** (type-directed random module generator; compares results and trap-ness) | **required** |
| 5 | **Disassembler** (binary → WAT, round-trips) | stretch |
| 6 | **Execution tracer/profiler** with HTML report (hot instructions, call counts, fuel metering) | stretch |
| 7 | Fuel limits / deterministic timeout (part of 6) | stretch |

## Done means
Every gate in the daily-build brief; differential fuzz green on thousands of modules; `cargo test` green.
