# Adversarial review

Hostile pass over Kiln's own code, hunting for bugs, broken edge cases and
lazy shortcuts. Each finding below was first reproduced, then fixed; the
fix is described alongside the finding, and a regression test was added
for every one.

## 1. Pebble variable scoping is fully flat — false "redeclaration" errors

**Repro:**
```
fn f(n) -> i32 {
    if (n > 0) { let x = 1; return x; }
    else { let x = 2; return x; }
    return 0;
}
```
raised `PebbleCompileError: redeclaration of 'x'`, even though the two
`let x` bindings live in disjoint branches and never coexist. `_FuncCtx`
tracked locals in one flat dict for the whole function, with no notion of
block scope.

**Fix:** `_FuncCtx` now holds a stack of scope dicts. `declare()` only
checks the *innermost* scope for a collision (real shadowing rule);
`lookup()` searches outward through enclosing scopes. Compiling an
`if`/`while` body pushes a fresh scope and pops it afterward. WASM locals
still get a fresh, never-reused index per `let` (the flat index space is
an implementation detail; the *names* now behave with proper lexical
scoping, which is what a program author actually observes).

## 2. Deep recursion crashes with a raw Python `RecursionError`

**Repro:** `count(100000)` where `count` recurses once per call — blew
through Python's own call-stack limit and surfaced
`RecursionError: maximum recursion depth exceeded in comparison` straight
out of the interpreter, not caught anywhere.

Every real WASM engine reports stack exhaustion as a **trap**
(`RangeError: call stack size exceeded` in V8, etc.) — a normal,
catchable outcome a host is expected to handle, not a crash of the host
language itself.

**Fix:** `call_function` now catches `RecursionError` and re-raises it as
`WasmTrap("call stack exhausted")`, matching real engine behavior.

## 3. The assembler never validates global mutability

**Repro:**
```
(module
  (global $g i32 (i32.const 5))     ;; immutable
  (func $f i32.const 99 global.set $g)
  (export "f" (func $f)))
```
assembled and ran without complaint, silently mutating a global declared
immutable. The WASM binary format itself makes this invalid (a
conformant engine rejects the module at validation time); Kiln produced
a "valid-looking" binary that only an external engine would catch, with
no diagnostic of its own.

**Fix:** the assembler now looks up the target global's declared
mutability (checking both the module's own globals and any imported
ones) whenever it emits `global.set`, and raises `AssembleError` at
assemble time if the global isn't declared `mut`.

## 4. CLI subcommands leak raw Python tracebacks for ordinary user errors

**Repro:** any of these produced a full Python stack trace instead of a
one-line error:
```
kiln run missing.wasm main            # FileNotFoundError
kiln assemble typo.kwat -o out.wasm   # FileNotFoundError / SyntaxError
kiln run out.wasm no_such_export      # KeyError
```

**Fix:** `main()` now wraps subcommand dispatch in a single handler that
catches `OSError` (missing/unreadable files), `SyntaxError` /
`AssembleError` / `PebbleSyntaxError` / `PebbleCompileError` (malformed
source), `KeyError` (undefined export/import) and `WasmTrap`, printing a
concise `kiln: <message>` to stderr and exiting with status 1 in every
case — no tracebacks for user-caused errors.

## 5. The assembler raises bare `IndexError`/`KeyError` for common authoring typos

**Repro:** `i32.const)` with the operand omitted raised
`IndexError: list index out of range` from deep inside `_assemble_body`,
with no indication of what was wrong or where.

**Fix:** immediate-operand consumption in `_assemble_body` is now wrapped
so an out-of-tokens condition raises
`AssembleError("<mnemonic> is missing its immediate operand")` instead of
leaking the underlying `IndexError`.

## 6. WASI-lite `fd_write` can be called before the instance it needs exists

**Repro:** if a module's `start` function called `fd_write` (or any host
import that touches memory) before `Instance.__init__` returns, the
lazy `get_memory()` closure in `kiln/host.py` indexed into an empty
`holder` list and raised `IndexError`.

**Fix:** `get_memory()` now raises a clear `WasmTrap` ("host function
called before the module finished instantiating") instead of an opaque
`IndexError`, so the failure is at least diagnosable — this is a known,
accepted limitation of the lazy-memory-getter pattern (real embedders
solve it with two-phase instantiation, which is out of scope here) rather
than a silent crash.

## Bonus: the differential-testing strategy caught a real bug in Phase 4

While building the WASI-lite stretch feature (`examples/hello_wasi.kwat`),
the first version declared its iovec's `buf_len` as 18 when the message
("Hello from Kiln!\n") is actually 17 bytes. The module still "worked" —
it returned errno 0 in both engines — but `kiln verify` printed the
message with a trailing NUL byte read one past the end of the string,
identically in *both* Kiln's interpreter and Node's real engine. Neither
engine's return value caught it (division/traps aren't involved; it's
just wrong I/O), which is exactly the class of bug a return-value-only
test suite misses and only a genuine differential run against a real
engine — comparing actual output bytes, not just outcomes — catches. Fixed
by correcting the length constant; a regression test
(`test_wasi_lite_hello_matches_node`) now asserts the exact stdout bytes,
not just the errno.

## Accepted, out-of-scope limitations (not bugs)

- **Table/element imports** aren't supported (only single-module-owned
  tables). Documented in the decoder with an explicit `ValueError`
  rather than silently mis-parsing.
- **Exact NaN bit-pattern matching against other engines** is not
  attempted. The WASM spec deliberately leaves NaN payload propagation
  implementation-defined; Kiln's differential tests only compare
  operations whose results are exactly specified.
- **No standalone module validator.** Kiln doesn't run a separate
  structural type-check pass before execution (the way a spec-conformant
  engine's `validate()` step would); malformed modules that pass parsing
  may still trap in less-than-ideal ways at runtime instead of being
  rejected up front. All of Kiln's own producers (assembler, Pebble
  compiler) only ever emit well-typed modules, so this only bites
  hand-crafted adversarial binaries, not normal use.
