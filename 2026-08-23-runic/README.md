# Runic

> Status: **Phase 5 — verification complete.** 73 unit tests (lexer,
> parser, typechecker, interpreter, disassembler, CLI, and the full
> dual-oracle corpus, wired into `unittest`) plus `demo.sh`, an end-to-end
> script exercising every feature, all green. Two real bugs were found and
> fixed during Phase 3's adversarial review (see
> [`REVIEW.md`](./REVIEW.md)) — one a genuine encoder bug Node's engine
> outright rejected, the other a silent wrong-answer bug invisible to
> single-loop programs. Both were caught by the dual-oracle verifier
> itself, not by inspection, and are now permanent regression tests.

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

# run the full unit test suite (lexer/parser/typecheck/interpreter/disasm/CLI/dual-oracle)
python3 -m unittest discover -s tests -v

# or exercise every feature end to end in one shot
./demo.sh
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
8. ✅ *(Phase 4 bonus, beyond the plan)* `assert(cond);` — a language-level
   contract check compiled straight to WASM's own `unreachable` trap
   opcode, so a failed assertion is a real spec-level trap verified
   against Node exactly like divide-by-zero — see `demo/assertions.rn`

## The dual-oracle actually caught real bugs

Building this against a second, independent implementation wasn't
theoretical — `verify.py` caught two genuine bugs during development:

1. A control-flow frame leak in the interpreter: an `if` with no `else`
   branch skipped straight past its `end` opcode when the condition was
   false, never popping the frame it had pushed, silently corrupting
   `br`/`br_if` depth math for every later branch in the same call. It
   was invisible on every single-loop program (`fib`, `factorial`, `gcd`,
   `is_prime` all passed) and only surfaced once a program nested a
   conditional two `while` levels deep (`bubble_sort.rn`).
2. A non-canonical LEB128 encoding bug: an unsigned-looking literal like
   `4294967295` (meant to be `-1`'s bit pattern) compiled and even *ran*
   correctly under our own lenient decoder — but Node's real, spec-strict
   engine **rejected the module outright** on load.

Both are exactly the kind of bug that ships silently when a compiler and
its interpreter are only ever checked against each other. See
[`REVIEW.md`](./REVIEW.md) for the full writeup, plus two more findings
(unhandled CLI error paths, and unbounded recursion crashing instead of
trapping) that were UX bugs rather than correctness bugs.

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
demo.sh             end-to-end script exercising every feature (Phase 5)
tests/              73 unit tests: lexer, parser, typecheck, interpreter,
                    disassembler, CLI (subprocess), dual-oracle corpus
```
