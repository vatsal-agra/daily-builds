# Kiln

A from-scratch WebAssembly toolchain in pure Python: a real `.wasm` binary
decoder/encoder, a stack-machine interpreter, a text assembler, and a tiny
compiled language ("Pebble") that targets it.

**Status: Phase 2 (core build) complete.** All four required features work
end-to-end: the binary decoder/encoder round-trips real `.wasm` modules
byte-for-byte, the interpreter executes the WASM instruction set and is
cross-checked against Node's real `WebAssembly` engine, the `.kwat` text
assembler builds modules by hand, and the Pebble compiler turns a small
imperative language into running WASM. 49/49 tests pass (`python3 -m
unittest discover -s . -t . -p 'test_*.py'` from this directory).

See [PLAN.md](./PLAN.md) for the architecture and feature list.

## Quick tour

```
python3 -m kiln.cli assemble examples.kwat -o out.wasm   # (see kiln/asm)
python3 -m kiln.cli compile fib.pebble -o fib.wasm
python3 -m kiln.cli run fib.wasm fib 10
python3 -m kiln.cli disasm fib.wasm
```

Next: adversarial review (Phase 3).
