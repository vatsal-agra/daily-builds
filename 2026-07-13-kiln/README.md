# Kiln

A from-scratch WebAssembly toolchain in pure Python: a real `.wasm` binary
decoder/encoder, a stack-machine interpreter, a text assembler, and a tiny
compiled language ("Pebble") that targets it.

**Status: Phase 4 (stretch + polish) complete.** All four required
features work end-to-end, six real bugs found by a hostile self-review
pass have been fixed with regression tests (see [REVIEW.md](./REVIEW.md)),
and both stretch features have shipped: a self-contained interactive HTML
execution visualizer and real WASI-lite host imports (which caught a
genuine off-by-one bug via differential testing — see REVIEW.md). 59/59
tests pass (`python3 -m unittest discover -s . -t . -p 'test_*.py'` from
this directory).

See [PLAN.md](./PLAN.md) for the architecture and feature list.

## Quick tour

```
python3 -m kiln.cli assemble examples/hello_wasi.kwat -o hello.wasm
python3 -m kiln.cli compile examples/fib.pebble -o fib.wasm
python3 -m kiln.cli run fib.wasm main
python3 -m kiln.cli disasm fib.wasm
python3 -m kiln.cli verify fib.wasm fib 10          # cross-check vs Node's real WASM engine
python3 -m kiln.cli trace fib.wasm fib 6 --html -o trace.html   # interactive visualizer
```

`viz/index.html` ships a pre-baked `fib(6)` trace — open it directly in a
browser, no build step.

Next: verification (Phase 5).
