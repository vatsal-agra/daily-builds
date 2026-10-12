# Wick — adversarial review (Phase 3)

I attacked the Phase 2 build as a hostile reviewer would: not "does the demo work" but "what breaks it,
and how would I know if the test harness were lying". Method:

1. **Round-trip attack** — every generated program must survive `encode → decode → encode` byte-for-byte
   and `disassemble → parse → compare` structurally.
2. **Hostile inputs** — oversized memories, deep nesting, runaway recursion, enormous frames, out-of-range
   literals, truncated/garbled text and binaries.
3. **Differential attacks against V8** — (a) execution, (b) validation of ~50k corrupted/mutated modules,
   (c) a hand-written conformance corpus whose *expected values are themselves replayed on V8*.
4. **Is the oracle alive?** — inject known bugs into Wick and confirm each harness notices.
5. **Real compiler output** — C compiled by clang to wasm32 must agree with the same C compiled natively.
6. **Code-smell sweep** — dead code, duplicate logic, misleading messages.

## Findings (all fixed; each has a regression check listed)

| # | Severity | Finding | How it was found | Fix | Regression guard |
|---|----------|---------|------------------|-----|------------------|
| 1 | **bug** | WAT `br_table` swallowed every following atom, including the next flat instruction (`br_table 2 0` + `end` → "unknown label `end`"). Disassembler output could not be re-assembled. | round-trip over generated programs (seed 1) | only index-like atoms (`$id` / digits) are consumed; same for `call_indirect`'s optional table | `tests/roundtrip.rs` (1500 programs) |
| 2 | **bug** | Block types were resolved through the function-type path, which silently *registered* `[]→[]`, `[]→[i64]`… in the type section, so text round-trips grew the type table. | same test, seed 1 | dedicated `block_type` that only creates a type when params/multi-results need one | `tests/roundtrip.rs` compares `types` exactly |
| 3 | **crash** | `(memory 65536)` tried to allocate 4 GiB → process abort (OOM) instead of an error. Tables had the same problem (`u32::MAX` elements). | hostile-input battery | instantiation returns a `link error` above a documented cap (8192 pages / 10M elements) | `tests/corpus/instantiation.wat` |
| 4 | **crash** | A function with 40 000 locals recursing 10 000 deep needs ~3 GiB of value stack; only call *depth* was limited. | hostile-input battery | global value-stack cap (16 M slots); trap `call stack exhausted` | manual hostile run recorded in `tests/hostile.sh` |
| 5 | **crash** | 5 000 nested `(` overflowed the Rust stack in the recursive-descent s-expression parser. | hostile-input battery | nesting limit of 400 with a positioned error | `tests/hostile.sh` |
| 6 | **spec bug** | `f32.const 1e39` silently became `inf`; the spec says an out-of-range literal is malformed. | reading the spec against the parser | literals that overflow to infinity are rejected (explicit `inf` still works) | `tests/corpus/malformed.wat` |
| 7 | **spec bug** | `local` count limit (50 000) was only enforced by the binary decoder, so text-built modules could exceed it. | code audit | enforced in the validator | validator differential |
| 8 | **bug** | Invoking an *imported* function directly through the API trusted the host's return values without checking arity/types, so a bad host closure could poison the value stack. | code audit | same signature check as for calls made from wasm code | `tests/api.rs` |
| 9 | **gap** | `datacount` section (id 12) — emitted by real toolchains whenever bulk memory is on — was rejected as "unknown section". | thinking about clang output, confirmed with `clang -mbulk-memory` | accepted, ordered between element and code, count cross-checked | `tests/api.rs` (hand-built binary) |
| 10 | **gap** | Multi-memory memarg encodings (align bit 6) were reported as a baffling "alignment 2^65" error. | validator differential vs V8 | clear "multi-memory … is not supported" decode error | `diff/validate_diff.js` classifies it as an expected V8-only feature |
| 11 | **ugly UX** | `f32` results were printed after widening to `f64` (`0.1f32` → `0.10000000149011612`); huge/small magnitudes printed 300 digits. | CLI sweep | shortest-round-trip formatting in the value's own width, scientific notation outside 1e-5…1e16 | `tests/api.rs` |
| 15 | **bug** | `wick validate empty.wasm` said *valid*: any file not starting with `\0asm` was parsed as text, and an empty text file is an empty module. A garbled `.wasm` was therefore reported as a (different) text error or, worse, accepted. | `tests/hostile.sh` | files ending in `.wasm` are always decoded as binary; an empty/comment-only text file is a "no module found" error | `tests/hostile.sh` |
| 12 | **test-quality** | First fuzz generator version was **66 % traps** (every second `call_indirect` hit an empty table slot, `unreachable` and OOB addresses were too common), so most programs died before reaching deep code. | trap-category histogram | trap sources thinned; divisors forced non-zero 88 % of the time; failing `call_indirect` variants only 8 %. Down to ~27 % traps while still covering every trap kind | histogram in README / `diff/diff.js` summary |
| 13 | **test-quality** | 7 of my *hand-computed expected values* in the corpus were wrong (e.g. an unaligned `i32.load` at offset 1, `memmove` result). None were Wick bugs. | the V8 replay of the corpus disagreed with my expectations | expectations corrected to the independently-verified values; the corpus is now checked on both engines every run | `node diff/corpus.js` |
| 14 | **test-quality** | Corpus modules written for the validator tests were themselves invalid in unintended ways (a `br_table` that was in fact valid; an `invalid` directive with an empty message that was silently ignored). | corpus replay on V8 | fixed the cases; the Rust runner now fails loudly on a malformed directive set | `tests/corpus.rs` |

## "Is the harness alive?" — mutation checks of my own oracles

A differential test that never fails proves nothing. I injected bugs and confirmed each harness catches them:

| injected bug | detected by | result |
|---|---|---|
| `f32.nearest` rounds ties away from zero instead of to even | `diff/diff.js` | 7 / 1000 programs disagree, reported with the global that differs |
| validator stops checking that `select` operands agree | `diff/validate_diff.js` | 27 / 12 000 mutants flagged "validator too lax", with V8's reason |

(Both bugs were reverted; the numbers above are from the injected runs.)

## Known, deliberate limits (not bugs — documented so nobody mistakes them for omissions)

* Post-MVP features outside the supported set (reference types, SIMD, threads, exceptions, GC, multi-memory,
  passive/declarative segments, `memory.init`, `table.*`) are rejected by the decoder with a specific message.
* Supported extras beyond MVP: sign-extension ops, non-trapping float→int conversions, multi-value
  (block params + multiple results), `memory.copy` / `memory.fill`, `select t`.
* One memory and one table per module. Imported mutable globals are not supported (import link error).
* Wasm `NaN` payloads for *arithmetic* results are nondeterministic by spec; the fuzzer canonicalises them so
  engines can be compared bit-for-bit elsewhere.

## Fresh run-through (the gate)

After the fixes I re-ran everything from a clean state; **none of the issues above reproduces**:

* `cargo test --release` — unit + round-trip + corpus + clang-vs-native + API tests: all green
* `wick fuzz --count 3000 --seed 90000` → `node diff/diff.js`: 3000/3000 programs, 49 563 calls agree with V8
* `wick mutants` (10 000 AST mutants) + byte-level mutants (21 000): 0 panics, 0 lax, 0 strict
* `node diff/corpus.js`: all directives agree with V8
* `tests/hostile.sh`: every hostile input ends in a clean error or trap, never a crash or hang
