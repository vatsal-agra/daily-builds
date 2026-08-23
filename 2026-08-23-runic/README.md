# Runic

> Status: **Phase 2 — core build complete.** All 4 required features work
> end-to-end and are cross-checked against a real, independent WASM engine.

A from-scratch WebAssembly toolchain: a small i32 C-like language
("Runic"), compiled by a hand-written front end into genuine WASM binary
format, executed by a hand-written stack-machine interpreter, and verified
against **Node's real `WebAssembly` engine** as an independent oracle.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature rationale.

## Quick start

```sh
# compile a .rn source file to a real .wasm binary
python3 cli.py compile demo/fib.rn -o fib.wasm

# run it through our own from-scratch interpreter
python3 cli.py run demo/fib.rn fib 10        # -> 55

# same .wasm, loaded by Node's native engine, for comparison
node -e "WebAssembly.instantiate(require('fs').readFileSync('fib.wasm')).then(({instance}) => console.log(instance.exports.fib(10)))"

# disassemble any .rn or .wasm file to WAT-like text
python3 cli.py disasm demo/gcd.rn

# generate an interactive step-through debugger (stack/locals/memory/pc)
python3 cli.py trace demo/bubble_sort.rn sort 10 -o trace.html

# run the dual-oracle differential verifier over the whole demo corpus
python3 cli.py verify        # or: python3 verify.py
```

## The Runic language

A minimal, i32-only C-like language — see `demo/*.rn` for real examples
(recursion, loops, arrays, short-circuit `&&`/`||`).

```c
fn fib(n) {
    if (n < 2) {
        return n;
    }
    return fib(n - 1) + fib(n - 2);
}

array buf[64];

fn fill_squares(n) {
    let i = 0;
    while (i < n) {
        buf[i] = i * i;
        i = i + 1;
    }
    return 0;
}
```

Every function must return `i32` on every code path (checked at compile
time); every value is `i32`; there is no `break`/`continue`/`goto`, which
keeps codegen's branch-depth arithmetic fully static.

## Feature list

**Required:**
1. ✅ Runic language front end (lexer → recursive-descent parser →
   scope/arity/return-path checker) — `compiler/{lexer,parser,typecheck}.py`
2. ✅ From-scratch WASM binary encoder (real MVP format: LEB128, sections,
   structured control flow) — `compiler/encoder.py`
3. ✅ From-scratch WASM binary decoder + stack-machine interpreter,
   independent of the encoder — `compiler/interpreter.py`
4. ✅ Dual-oracle differential verifier (our interpreter vs. Node's native
   `WebAssembly` engine, over a 9-program corpus, value-for-value and
   trap-for-trap) — `verify.py` + `oracle.mjs`

**Stretch:**
5. ✅ Linear memory + global arrays (`array name[N]`, with optional
   initializer → real WASM data segments) — see `demo/sieve.rn`,
   `demo/bubble_sort.rn`
6. ✅ WASM disassembler (`compiler/disasm.py`, decoder-based, not
   encoder-coupled)
7. ✅ Interactive single-file HTML step-through visualizer
   (`compiler/viz.py` + `cli.py trace`)

## The dual-oracle actually caught a real bug

Building this against a second, independent implementation wasn't
theoretical: `verify.py` caught a genuine control-flow bug in the
interpreter during development — an `if` construct with no `else` branch
leaked its control-flow frame when skipped (never reaching the `end`
opcode that would normally pop it), silently corrupting `br`/`br_if`
depth math for every *subsequent* branch in the same call. It was
invisible on single-loop programs (`fib`, `factorial`, `gcd`, `is_prime`
all passed) and only surfaced once a program nested a conditional inside
two levels of `while` (`bubble_sort.rn`) — exactly the kind of bug that
would have shipped silently if the interpreter were only ever checked
against its own compiler's output. See `REVIEW.md` for the full writeup.

## Layout

```
compiler/
  lexer.py        tokenizer
  parser.py        recursive-descent parser -> AST (ast_nodes.py)
  typecheck.py      scope/arity/return-path checking
  codegen.py        AST -> WASM instruction lists
  wasm.py           LEB128 codec, opcode table, format constants (shared)
  encoder.py        instruction lists -> real .wasm bytes
  interpreter.py     .wasm bytes -> decode -> stack-machine execution
  disasm.py         .wasm bytes -> WAT-like text
  viz.py            execution trace -> self-contained HTML debugger
  frontend.py       source -> .wasm pipeline glue
demo/               example Runic programs used by verify.py and the CLI
oracle.mjs          Node script: loads .wasm into V8's real WebAssembly engine
verify.py           dual-oracle differential test harness (the CLI's `verify`)
cli.py              compile / run / disasm / trace / verify
tests/              unit test suite (Phase 5)
```
