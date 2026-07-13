# Kiln

A from-scratch WebAssembly toolchain in pure Python: a real `.wasm` binary
decoder/encoder, a stack-machine interpreter, a text assembler, and a tiny
compiled language ("Pebble") that targets it.

**Status: Phase 3 (adversarial review) complete.** All four required
features work end-to-end and six real bugs found by a hostile self-review
pass have been fixed with regression tests — see [REVIEW.md](./REVIEW.md).
58/58 tests pass (`python3 -m unittest discover -s . -t . -p 'test_*.py'`
from this directory).

See [PLAN.md](./PLAN.md) for the architecture and feature list.

## Quick tour

```
python3 -m kiln.cli assemble examples.kwat -o out.wasm   # (see kiln/asm)
python3 -m kiln.cli compile fib.pebble -o fib.wasm
python3 -m kiln.cli run fib.wasm fib 10
python3 -m kiln.cli disasm fib.wasm
python3 -m kiln.cli verify fib.wasm fib 10   # cross-check vs Node's real WASM engine
```

Next: stretch features + polish (Phase 4).
