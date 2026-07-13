# Kiln

A from-scratch WebAssembly toolchain, in pure Python: a real `.wasm`
binary decoder/encoder, a stack-machine interpreter, a WAT-inspired text
assembler, and a tiny compiled language ("Pebble") that targets it —
plus an interactive HTML execution visualizer and WASI-lite host imports.

Every module Kiln produces is a real, standard `.wasm` binary. It's not
self-consistent by construction — it's checked against Node's own
`WebAssembly` engine, so "correct" means "a real production runtime
agrees," not just "Kiln agrees with itself."

## Why this, today

Every prior "build a VM from scratch" project in this repo invents its
own bytecode. Kiln instead targets a real, externally-specified,
already-standardized format. That one choice changes what "correct" can
mean: instead of only self-consistency, every module Kiln builds can be
run byte-for-byte on a completely independent, production-grade engine
(Node's native `WebAssembly`) and diffed. That differential-testing
harness isn't decorative — it caught a real off-by-one bug in the
WASI-lite demo during Phase 4 that a return-value-only test would have
missed entirely (see [REVIEW.md](./REVIEW.md)). Building a real compiler
front end (Pebble) *and* a real VM back end *and* an independent
oracle to check them against, in one day, felt like the most complete
version of "systems programming toy" available.

## How to run it

```bash
cd 2026-07-13-kiln

# Full test suite (59 tests, pure stdlib unittest — no pytest needed)
python3 -m unittest discover -s . -t . -p 'test_*.py'

# Full end-to-end walkthrough through the actual CLI
./demo.sh

# Try it yourself
python3 -m kiln.cli assemble examples/hello_wasi.kwat -o hello.wasm
python3 -m kiln.cli run hello.wasm main                # prints "Hello from Kiln!"

python3 -m kiln.cli compile examples/fib.pebble -o fib.wasm
python3 -m kiln.cli run fib.wasm main                   # fib(10) = 55
python3 -m kiln.cli disasm fib.wasm                       # readable text form
python3 -m kiln.cli verify fib.wasm fib 10                 # cross-check vs Node
python3 -m kiln.cli trace fib.wasm fib 6 --html -o t.html    # interactive visualizer
```

`viz/index.html` ships a pre-baked `fib(6)` trace — open it directly in a
browser (no server, no build step) to see the visualizer without running
anything.

Node.js is used only as an independent verification oracle
(`kiln verify`, `kiln.cli trace`'s testing, the `test_node_diff.py`
suite) — Kiln itself has zero runtime dependencies, pure Python 3
stdlib only.

## Feature list

**Required (all four fully implemented, no stubs):**

1. **Binary decoder + encoder** (`kiln/wasm/decoder.py`,
   `kiln/wasm/encoder.py`) — parses real `.wasm` modules (type, import,
   function, table, memory, global, export, start, element, code, data
   sections; LEB128 varints) into an in-memory IR and back, byte-for-byte,
   verified in `test_decoder_encoder.py`.
2. **Stack-machine interpreter** (`kiln/wasm/interpreter.py`) — executes
   the WASM MVP instruction set: full i32/i64/f32/f64 numeric ops,
   structured control flow (block/loop/if/br/br_if/br_table), function
   calls including `call_indirect` through a real table + element
   segments, locals/globals, linear memory load/store with correct
   width/alignment/sign semantics, and traps (division by zero, integer
   overflow, out-of-bounds memory, stack exhaustion). Cross-checked
   instruction-by-instruction against Node's real engine.
3. **`.kwat` text assembler** (`kiln/asm/`) — a WAT-inspired s-expression
   format (lexer → s-expr reader → two-pass symbol-resolving assembler)
   that hand-authors real WASM binaries: named locals/globals/functions/
   labels/types, forward references, memory/table/data/element segments.
4. **Pebble compiler** (`kiln/pebble/`) — a small imperative language
   (functions, `if`/`else`, `while`, recursion, arithmetic, short-circuit
   `&&`/`||`, proper lexical block scoping) with a real
   lexer → recursive-descent parser → AST → WASM-emitting compiler.
   Pebble programs run end-to-end inside Kiln's own interpreter.

**Stretch (both shipped):**

5. **Interactive HTML execution visualizer** (`viz/`, `kiln/trace.py`,
   `kiln trace --html`) — records a full step-by-step trace (operand
   stack, locals, call stack/depth) and bakes it into a self-contained
   single-file page with play/pause/step/scrub controls. Verified with
   Playwright in headless Chromium (no JS errors; works in light and
   dark themes).
6. **WASI-lite host imports** (`kiln/host.py`) — `env.print` and a real
   `wasi_snapshot_preview1.fd_write` (the actual WASI ABI shape: fd,
   iovs pointer/len, nwritten pointer) so a Pebble/`.kwat` program can
   produce real stdout output through normal import linking, not a
   shortcut. See `examples/hello_wasi.kwat`.

**Also included:** a `kiln verify` CLI command and `kiln disasm`
disassembler; six real bugs found and fixed by an adversarial
self-review pass (scoping, stack-overflow handling, immutable-global
validation, CLI error UX, assembler robustness — full writeup in
[REVIEW.md](./REVIEW.md)); 59 unit tests plus `demo.sh` driving the
actual CLI end-to-end.

## Architecture

See [PLAN.md](./PLAN.md) for the full breakdown. In short:
`kiln/wasm/` is the binary format + VM (format-agnostic of how a module
was produced); `kiln/asm/` and `kiln/pebble/` are two independent module
*producers* that both emit the same `types.Module` IR and hand it to
`kiln/wasm/encoder.py`; `kiln/trace.py` and `kiln/host.py` hook into the
interpreter without it needing to know they exist (`instance.tracer` and
the import-linking table are the only touchpoints).

## Where a human could take this next

- **Multi-value blocks / reference types / SIMD** — Kiln implements the
  original WASM MVP; the newer proposals (multi-value returns, table
  imports, `v128`) are unimplemented but the IR has room for them.
- **A real validator pass** — right now malformed hand-crafted binaries
  can reach the interpreter and trap in less-than-ideal ways instead of
  being rejected at load time, the way a spec-conformant engine's
  `validate()` would. Worth adding as a real type-checking pass over the
  IR before execution.
- **Compile Kiln's own interpreter to WASM** — since Pebble already
  targets Kiln's own VM, a fun next step is self-hosting: get Pebble (or
  a bigger language on top of it) to the point it can express a WASM
  interpreter, and run Kiln inside Kiln.
- **A real optimizing pass over Pebble's output** — right now the
  compiler does zero optimization (no constant folding, no dead-code
  elimination); there's a lot of instruction-count fat to trim.
- **Browser demo** — `viz/index.html` already runs anywhere; pairing it
  with a `wasm-bindgen`-style JS shim that runs *Kiln's own compiled
  Pebble modules* directly in a real browser tab (not just Node) would
  close the loop nicely.
