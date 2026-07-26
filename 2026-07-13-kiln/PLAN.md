# Kiln — a from-scratch WebAssembly toolchain

## Concept

WebAssembly is the one bytecode format almost every modern platform can run
natively — browsers, Node, edge runtimes, blockchains, plugin systems. Kiln
is a complete WASM toolchain built from first principles in pure Python:

- **A binary decoder/encoder** for the real `.wasm` module format (LEB128
  varints, section layout, type/function/code/export/memory/global sections)
- **A stack-machine interpreter** that executes real WASM bytecode — control
  flow (block/loop/if/br/br_if/br_table), the full i32/i64/f32/f64 numeric
  instruction set, locals, globals, and linear memory
- **A text assembler** (`.kwat`, WAT-inspired s-expressions) so modules can be
  hand-authored without an external toolchain
- **Pebble**, a tiny imperative source language (functions, if/while,
  arithmetic, recursion) with its own lexer/parser/compiler that emits real
  WASM binaries runnable by Kiln — a genuine compiler front end bolted onto
  a genuine VM back end

## Why it's interesting

Every other angle on "build a VM from scratch" in this repo's history (Coil,
the SAT solvers, the path tracers) invents its own bytecode. Kiln targets a
**real, standardized, externally-specified format** — which means correctness
isn't just self-consistency, it's conformance. This repo's sandbox happens to
have Node.js with a native `WebAssembly` global, so every module Kiln
produces (from the assembler or from Pebble) can be differentially tested
against a *real* production WASM engine: encode with Kiln, run in Kiln,
run the identical bytes in Node, diff the results. That's a much stronger
verification story than "my interpreter agrees with itself."

## Architecture

```
kiln/
  wasm/
    leb128.py       — LEB128 varint encode/decode (unsigned + signed)
    types.py         — value types, Module IR dataclasses, ValType enum
    opcodes.py        — opcode table (name <-> byte, per-opcode operand shape)
    decoder.py        — .wasm binary bytes -> Module IR
    encoder.py         — Module IR -> .wasm binary bytes
    interpreter.py      — stack-machine executor over a decoded Module
  asm/
    lexer.py          — .kwat tokenizer
    parser.py          — s-expression parser -> instruction list
    assembler.py         — text IR -> Module IR (reuses encoder to emit bytes)
  pebble/
    lexer.py           — Pebble source tokenizer
    parser.py            — recursive-descent parser -> Pebble AST
    compiler.py            — AST -> WASM function bodies + Module IR
  cli.py                    — kiln assemble/run/compile/disasm/verify subcommands
  disasm.py                  — Module IR -> readable text (round-trip check)
tests/
  test_leb128.py
  test_decoder_encoder.py     — round-trip fuzz: random modules survive encode/decode
  test_interpreter.py          — hand-written .wasm bytecode, checked instruction by instruction
  test_assembler.py             — .kwat programs assembled and executed
  test_pebble.py                  — Pebble programs compiled, executed, checked
  test_node_diff.py                — cross-check against Node's real WebAssembly engine (skipped if node missing)
tools/
  node_runner.js                    — tiny harness: load a .wasm file, call an export, print JSON result
viz/
  index.html                          — self-contained interactive stack/memory/trace visualizer
demo.sh
```

## Feature list

1. **[required] Binary decoder + encoder** — round-trips real `.wasm` module
   bytes (type/import/function/table/memory/global/export/code/data
   sections) through an in-memory IR with byte-for-byte fidelity.
2. **[required] Stack-machine interpreter** — executes the WASM instruction
   set (numeric ops for i32/i64/f32/f64, control flow incl. structured
   branches and function calls, locals, globals, linear memory
   load/store with correct alignment/width semantics), verified
   differentially against Node's native `WebAssembly` runtime.
3. **[required] `.kwat` text assembler** — a WAT-inspired s-expression text
   format compiled to real WASM binaries, so test modules can be authored
   by hand without any external tool.
4. **[required] Pebble compiler** — a small imperative language (ints,
   functions, if/while, recursion, arithmetic/comparison) with a real
   lexer → parser → AST → WASM-emitting compiler; Pebble programs run
   end-to-end inside Kiln's own interpreter.
5. **[stretch — shipped] Interactive HTML visualizer** — `kiln trace
   mod.wasm func args... --html -o out.html` records a step-by-step
   execution trace (operand stack, locals, call stack, depth) and bakes it
   into a self-contained, single-file HTML page with play/pause/step/scrub
   controls (`viz/index.html`, `viz/template.html`). Verified rendering
   and interaction with Playwright in headless Chromium — no JS errors,
   works in both light and dark themes.
6. **[stretch — shipped] WASI-lite host imports** — `env.print` and a real
   `wasi_snapshot_preview1.fd_write` (the same ABI shape a real WASI
   runtime exposes) let a Pebble/`.kwat` program produce actual stdout
   output through the normal import-linking path, not a shortcut. See
   `examples/hello_wasi.kwat`, cross-checked against Node in
   `test_wasi_lite_hello_matches_node`.

## Verification strategy

Because Node ships a real, spec-compliant WASM engine, Kiln's biggest risk
(quietly-wrong semantics that only agree with themselves) is mitigated by a
differential oracle: every module built during tests is executed both by
Kiln's Python interpreter and by Node's `WebAssembly.instantiate`, and the
results are asserted equal. This is the same strategy last month's Graft
project used against real `git`.
