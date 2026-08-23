# Runic — Plan

## Concept

**Runic** is a complete, from-scratch WebAssembly toolchain for a small
i32-only C-like language: a hand-written lexer/parser/typechecker, a
codegen pass that emits genuine WebAssembly **binary format** (the actual
MVP spec encoding — LEB128 integers, section IDs, type/function/code
sections, magic number + version header), a hand-written **stack-machine
interpreter** that executes that bytecode directly (no dependency on any
WASM runtime), and a **dual-oracle verifier** that loads the exact same
`.wasm` bytes into Node's native `WebAssembly` engine and asserts our
interpreter agrees with a real, independent implementation function call
for function call. A single-file HTML **step-through visualizer** turns a
compiled program into an explorable debugger (stack / locals / linear
memory / call frames / program counter, one instruction at a time).

## Why this is interesting

Most "toy compiler" projects stop at an AST-walking interpreter, which
never has to prove anything against an external authority — bugs in codegen
and bugs in the interpreter can silently cancel out. WebAssembly is
different: it's a real, versioned, byte-exact binary spec that a completely
independent, production-grade engine (V8's WASM engine, shipped inside
Node) already implements. That gives a **free, unforgeable oracle**: if my
hand-rolled binary encoder produces a byte sequence V8 refuses to parse, or
V8's result disagrees with my interpreter's result for the same function
and inputs, that is unambiguous proof of a real bug — not a matter of
opinion. Building both the producer (compiler → bytecode) and an
independent consumer (my own interpreter) of the same binary format, and
checking both against a *third*, external implementation, is a much
stronger correctness bar than a typical toy language project, and it
mirrors how real compiler backends are validated (differential testing
against a reference implementation).

## Architecture

```
source (.rn)
   │  lexer.py        → tokens
   │  parser.py        → AST
   │  typecheck.py      → typed AST (i32 everywhere, arity/scope checked)
   ▼
   codegen.py          → list of WASM instructions per function (structured
                          control flow: block/loop/if matching WASM's model)
   ▼
   encoder.py           → real WASM binary format bytes (magic, version,
                          type/import/function/memory/export/code sections,
                          LEB128 varint/varsint encoding throughout)
   ▼
  .wasm bytes  ──────────────┬─────────────────────────┐
                              ▼                          ▼
                      interpreter.py             oracle_node.mjs
                 (from-scratch decoder +      (Node's real WebAssembly
                  stack-machine executor,      engine loads the exact
                  independent of codegen)       same bytes)
                              │                          │
                              └────────► compare ◄───────┘
                                     (verify.py harness)
```

Everything is pure Python 3 stdlib on the compiler/interpreter side (no
`wasmtime`, no `pywasm`, no parser-generator library — lexer, recursive
descent parser, and LEB128 codec are all hand-written). The oracle side
uses Node's *built-in* `WebAssembly` global, which every Node install
ships — no npm package installed, so it's a truly independent
implementation, not code we wrote.

## Feature list

**Required (4):**

1. **Runic language front end** — lexer, recursive-descent parser, and a
   scope/arity typechecker for a small C-like i32 language: functions,
   `if`/`else`, `while`, local variables, integer arithmetic/comparison/
   logical ops, recursion, function calls.
2. **From-scratch WASM binary encoder** — real MVP binary format:
   `\0asm` header + version, LEB128 varuint/varsint encoding, type
   section (function signatures), function section, export section, code
   section with per-function local declarations and structured
   control-flow opcodes (`block`/`loop`/`if`/`br`/`br_if`/`call`/numeric
   ops), producing bytes a real engine can load.
3. **From-scratch WASM interpreter** — independent binary decoder +
   stack-machine executor (operand stack, control-flow label stack, local
   variable slots) that runs the emitted bytecode directly, with zero
   dependency on any WASM runtime.
4. **Dual-oracle differential verifier** — for a corpus of Runic programs,
   compile to `.wasm`, run every exported function through *both* our
   interpreter and Node's native `WebAssembly.instantiate` across a range
   of inputs, and assert byte-for-byte identical results. Any encoder or
   interpreter bug fails loudly here.

**Stretch (2+):**

5. **Linear memory + arrays** — `memory` section, `i32.load`/`i32.store`,
   data segments for string/array literals, and array syntax in the
   source language, visualized as a live memory grid in the debugger.
6. **WASM disassembler** — decode any `.wasm` module (ours or, best
   effort, third-party) back into readable WAT-like text, proving the
   decoder is a real, general binary-format reader and not something
   secretly coupled to our own encoder's exact output shape.
7. **Step-through HTML visualizer/debugger** — single self-contained file,
   one instruction at a time: operand stack, locals, call frames, linear
   memory, current opcode, with play/step/reset controls.

## Scope notes

Value type is **i32 only** (skip i64/f32/f64) — this keeps the type
system trivial so effort goes into a *correct, complete* pipeline for one
type rather than a shallow pipeline for four. i32 is enough for a real
language: integer arithmetic, control flow, recursion, arrays of ints.
