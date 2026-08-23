# Runic

A from-scratch WebAssembly toolchain: a small i32 C-like language
("Runic"), compiled by a hand-written front end into genuine WASM binary
format, executed by a hand-written stack-machine interpreter, and
cross-checked against **Node's real, independent `WebAssembly` engine**
as a differential oracle — not just against itself.

```
source (.rn) → lexer → parser → typecheck → codegen → real .wasm bytes
                                                            │
                                        ┌───────────────────┴───────────────────┐
                                        ▼                                       ▼
                          our own decoder + interpreter          Node's native WebAssembly engine
                                        └───────────────── compare ─────────────┘
```

## Why I built this today

Most "toy compiler" side projects stop at an AST-walking interpreter,
which never has to prove anything against an external authority — bugs in
codegen and bugs in the interpreter can silently cancel each other out and
the project just looks "done". WebAssembly is different: it's a real,
versioned, byte-exact binary spec that a completely independent,
production-grade engine (V8's, shipped inside every Node install) already
implements for free. That's a genuine, unforgeable correctness oracle,
and I wanted to see what building *against* one — rather than just
building a thing that runs — actually catches. The answer, concretely: it
caught two real bugs during development (see below) that would have
shipped silently in a self-consistent-only project, one of which was bad
enough that a real engine flatly refused to load the module at all. That
result is the reason this was worth a day.

## How to run it

```sh
# compile a .rn source file to a real .wasm binary
python3 cli.py compile demo/fib.rn -o fib.wasm

# run it through our own from-scratch interpreter
python3 cli.py run demo/fib.rn fib 10        # -> 55

# the exact same bytes, loaded by Node's native engine, for comparison
node -e "WebAssembly.instantiate(require('fs').readFileSync('fib.wasm')).then(({instance}) => console.log(instance.exports.fib(10)))"

# disassemble any .rn or .wasm file to WAT-like text
python3 cli.py disasm demo/gcd.rn

# generate an interactive step-through debugger (stack/locals/memory/pc)
python3 cli.py trace demo/bubble_sort.rn sort 10 -o trace.html

# run the dual-oracle differential verifier over the whole demo corpus
python3 cli.py verify        # or: python3 verify.py

# run the full unit test suite
python3 -m unittest discover -s tests -v

# or exercise every feature end to end in one shot
./demo.sh
```

No dependencies beyond Python 3 (stdlib only) and a working `node` binary
on `PATH` (used only as the oracle — never as part of the compiler or
interpreter themselves).

## The Runic language

A minimal, i32-only C-like language — every value is `i32`, every function
must provably return on every code path (checked at compile time), and
there is deliberately no `break`/`continue`/`goto`, which keeps codegen's
branch-depth arithmetic fully static. See `demo/*.rn` for real, verified
example programs (recursion, loops, arrays, short-circuit `&&`/`||`,
`assert`).

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

fn safe_div(a, b) {
    assert(b != 0);   // compiles to WASM's own 'unreachable' trap opcode
    return a / b;
}
```

## Feature list

**Required:**
1. ✅ **Runic language front end** — lexer → recursive-descent parser →
   scope/arity/return-path checker (`compiler/{lexer,parser,typecheck}.py`)
2. ✅ **From-scratch WASM binary encoder** — real MVP format: `\0asm`
   header, LEB128 varint/varsint, type/function/memory/export/code/data
   sections, structured control flow (`compiler/encoder.py`)
3. ✅ **From-scratch WASM binary decoder + stack-machine interpreter**,
   fully independent of the encoder — decodes sections, resolves
   block/loop/if control-flow targets in a one-time pass, executes with
   an operand stack + control-frame stack + local slots
   (`compiler/interpreter.py`)
4. ✅ **Dual-oracle differential verifier** — every call in a 12-program
   corpus runs through both our interpreter and Node's native
   `WebAssembly.instantiate` on the *exact same bytes*, asserting
   identical results, identical traps, and identical linear memory
   contents (`verify.py` + `oracle.mjs`)

**Stretch:**
5. ✅ **Linear memory + global arrays** — `array name[N]`, with optional
   `= {...}` initializer compiling to a real WASM data segment
   (`demo/sieve.rn`, `demo/bubble_sort.rn`)
6. ✅ **WASM disassembler** — decode any `.wasm` module back to WAT-like
   text, built against the general decoder rather than coupled to our own
   encoder's exact output shape (`compiler/disasm.py`)
7. ✅ **Interactive single-file HTML step-through debugger** — operand
   stack, locals, call depth, and a live linear-memory grid, one
   instruction at a time, generated from a real recorded execution trace
   (`compiler/viz.py` + `cli.py trace`)
8. ✅ **`assert(cond);`** — a language-level contract check compiled
   straight to WASM's own `unreachable` trap opcode, verified against
   Node exactly like divide-by-zero (`demo/assertions.rn`)

## The dual-oracle actually caught real bugs

This wasn't theoretical — `verify.py` caught two genuine bugs during
development (full writeup in [`REVIEW.md`](./REVIEW.md)):

1. **A control-flow frame leak in the interpreter.** An `if` with no
   `else` branch skipped straight past its `end` opcode when the
   condition was false, never popping the control-flow frame it had
   pushed — silently corrupting `br`/`br_if` depth math for every *later*
   branch in the same call. Invisible on every single-loop program
   (`fib`, `factorial`, `gcd`, `is_prime` all passed); it only surfaced
   once a program nested a conditional two `while` levels deep
   (`bubble_sort.rn` quietly produced a partially-sorted array).
2. **A non-canonical LEB128 encoding bug.** An unsigned-looking literal
   like `4294967295` (meant to be `-1`'s bit pattern) compiled and even
   *ran* correctly under our own lenient decoder — but Node's real,
   spec-strict engine **rejected the module outright** on load.

Both are exactly the kind of bug that ships silently when a compiler and
its interpreter are only ever checked against each other, and both are
now permanent regression tests in `verify.py` and `tests/`.

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
demo/               12 example Runic programs, also the verify.py/test corpus
oracle.mjs          Node script: loads .wasm into V8's real WebAssembly engine
verify.py           dual-oracle differential test harness (the CLI's `verify`)
cli.py              compile / run / disasm / trace / verify
demo.sh             end-to-end script exercising every feature
tests/              73 unit tests: lexer, parser, typecheck, interpreter,
                    disassembler, CLI (subprocess), dual-oracle corpus
PLAN.md             original architecture + feature plan (Phase 1)
REVIEW.md           adversarial review findings and fixes (Phase 3)
```

## Where a human could take this next

- **More value types.** i64/f32/f64 were deliberately out of scope (see
  PLAN.md) to keep the pipeline deep rather than the type system wide —
  adding them is mostly mechanical: more valtypes, more typed opcodes,
  and a real type-checked expression language instead of "everything is
  i32".
- **User-facing `break`/`continue`.** The language avoids them so every
  branch depth is statically known at codegen time; supporting them for
  real would mean threading a small "loop label stack" through codegen
  (not the interpreter, which already handles arbitrary `br`/`br_if`
  depths correctly) — a good next exercise precisely because it's a
  codegen problem, not an execution-model one.
- **Imports/host functions.** Right now every Runic program is a pure,
  closed set of i32 functions — no I/O. Supporting WASM imports would let
  Runic programs call host-provided functions (e.g. a `print` for actual
  output), which needs an import section in the encoder and import
  resolution in the interpreter — currently unimplemented.
- **A real register allocator / SSA-based optimizer.** Codegen currently
  emits WASM's stack-machine instructions directly and unopt from the
  AST — a constant-folding or dead-store-elimination pass over the
  instruction list before encoding would be a natural, well-scoped
  follow-up (and would give the dual-oracle verifier something new to
  prove correct).
- **Feed third-party `.wasm` files into the disassembler.** `disasm.py`
  was deliberately built against the general decoder, not coupled to our
  own encoder's output shape — trying it against real-world `.wasm` files
  (e.g. from `wat2wasm`/Rust/C output) would be a good stress test of
  that claim, and would likely surface WASM features (imports, tables,
  multi-value returns) the decoder doesn't handle yet.
