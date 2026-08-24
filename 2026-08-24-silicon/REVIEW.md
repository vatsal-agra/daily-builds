# Adversarial review

Conducted as a hostile reviewer: assume every subsystem is wrong until
proven otherwise by an independent check, not just "it ran once."
Verification strategy used throughout: cross-check the pipeline
simulator's final architectural state (register file + full memory image)
against the sequential golden-model simulator, across every example
program × every predictor (static/dynamic) × every cache configuration
(none, small/direct-mapped, larger/set-associative) combination — 35
program×config combinations in the final sweep, all passing after fixes.

## Bugs found and fixed

### 1. CRITICAL — speculative fetch of a *real* `ecall` word permanently wedged the pipeline

**Symptom:** `matmul.s` (the first program to exercise `jalr`/`ret`) never
halted; the pipeline simulator ran to `max_cycles` and every stage went
empty forever, with `fetch_halted` stuck `True` and `self.halted` never
becoming `True`.

**Root cause:** `ret` (`jalr x0, ra, 0`) resolves in EX, two cycles after
its own fetch. In between, the front-end speculatively fetches the
predicted fall-through — and because `ret` happened to be the *last*
instruction of the `mul` subroutine, textually immediately followed by
`end: ecall`, that fall-through fetch read the program's real, valid
`ecall` word. The original code set `self.fetch_halted = True` the moment
*any* fetched word decoded to `ecall`, with no regard for whether that
fetch was still speculative. Once set, nothing ever cleared it, even
though the branch that made this fetch speculative resolved (correctly)
one cycle later and flushed the pipeline registers holding it — the
*latch* was discarded, but the *side effect* on `fetch_halted` was not.

**Fix:** the halt decision is now made at the earliest point it's
*provably final*: after a candidate `ecall` instruction has been decoded
into `id_ex` **and** survived that same cycle's flush-override check (only
`if_id`/`id_ex` are ever flush targets in this design — once past that
boundary into `ex_mem`, nothing can retroactively squash an instruction).
The extra "one more" speculative fetch that inevitably happens on the
same cycle the real `ecall` is confirmed is now also explicitly discarded,
so it can never wrongly reach WB and fault.

### 2. CRITICAL — a genuinely illegal fetch anywhere in flight crashed the whole simulator

**Symptom:** the same `matmul.s` run initially crashed outright (before
bug #1's masking symptom was even reachable) with `ValueError: illegal
opcode ... in word 0x00000000` — raised from *inside* `_run_if_stage`,
the moment a still-speculative fetch happened to land on zeroed memory
past the end of the program.

**Root cause:** in-order hardware never faults on an instruction that
later turns out to be on a squashed path — but the original code called
`isa.decode()` eagerly at fetch time and let a `ValueError` propagate
immediately, with no way to tell "genuinely illegal" apart from "haven't
been flushed yet."

**Fix:** decode failures at fetch time are now caught and carried as a
soft `illegal: True` marker through the latches (mirroring how a real
CPU defers a fault to retirement). `_run_id_stage` and `_run_ex_stage`
pass such entries through as inert no-ops; only `_do_writeback` — i.e.
*true, unsquashed retirement* — turns a surviving illegal instruction
into a real `SimulatorTrap`.

### 3. CRITICAL — a mispredicted branch's flush could be silently clobbered by the very next instruction's own (unrelated) flush

**Symptom:** `bubblesort.s` under the **static** predictor (never under
dynamic, which is what let this hide during initial development)
diverged from the golden model — 194 retired instructions instead of the
correct 202, with the trace showing a `blt` that should have branched to
`doswap` instead falling through to the unconditional `j noswap`
immediately after it.

**Root cause:** `blt`/`bge`/etc. resolve in EX; `jal` (including the `j`
pseudo-instruction) resolves early, in ID, purely because its target
needs no register read. `_run_ex_stage` and `_run_id_stage` both run
*every* cycle regardless of what the other decides, and both wrote to the
same single `self._pending_flush` slot with no ordering guard. When a
branch mispredicted in EX *and*, on that exact same cycle, the
unconditional jump immediately behind it (its own predicted-not-taken
fall-through victim, still sitting in ID) resolved its own early jal
check, the **ID-stage write ran second and silently overwrote the
EX-stage write** — discarding the older, authoritative flush for the
newer, lower-priority one. `bubblesort.s`'s `blt t5, t4, doswap` /
`j noswap` pair is exactly this shape (a conditional branch immediately
followed by an unconditional jump over the not-taken case), which is why
it caught this and none of the straight-line-branch-only programs did.

**Fix:** the ID-stage jal-resolution path now only sets
`self._pending_flush` if it is still `None` — EX always runs first each
cycle, so a flush it already posted always wins, which is also always
*correct*: an EX-stage flush unconditionally discards `id_ex` too, a
strict superset of what the ID-stage jal flush would have discarded, so
there is never a case where preferring EX loses information.

### 4. Immediate-range validation silently accepted out-of-range signed offsets

**Symptom:** `sw t0, 2048(t1)` assembled without error into
`0x80532023` — but 2048 does not fit RISC-V's signed 12-bit store-offset
field (`-2048..2047`); the encoder silently wrapped it into a large
*negative* offset instead of rejecting it.

**Root cause:** the shared `_field()` immediate-validation helper checked
`-(1 << (bits-1)) <= value < (1 << bits)` — note the upper bound is `2×`
too generous for a signed field (for 12 bits: `< 4096` instead of the
correct `< 2048`). This affected every signed immediate in the ISA
(`addi`/`andi`/`ori`/etc., loads, stores, `jalr`, branches, `jal`).

**Fix:** split into `_signed_field` (correct symmetric range),
`_unsigned_field` (for `shamt`, which is genuinely unsigned 0..31), and
`_upper20_field` (the one legitimately dual-purpose case: `lui`/`auipc`'s
raw upper-20-bits pattern). Verified with a 470-case round-trip fuzz test
across every instruction format plus explicit boundary checks
(`2047`/`2048`/`-2048`/`-2049`).

### 5. Minor — a label-resolution error inside an operand lost its own line number

**Symptom:** `j nosuchlabel` reported `expected an integer literal, got
'nosuchlabel'` with no line number, unlike every other assembler error.

**Root cause:** `_resolve_branch_target` raises `AssemblerError` directly
(via `_parse_int`) without a line number, since it doesn't know its own
position; the pass-2 driver's `except AssemblerError: raise` re-raised it
completely unchanged instead of attaching the current line.

**Fix:** `AssemblerError` now keeps its pre-formatted `raw_message`
separately; the pass-2 driver fills in `line_no` on a line-less error
before re-raising it, so every assembler error is now consistently
located.

### 6. Minor — illegal instructions crashed the sequential golden model with a raw traceback

**Symptom:** running any program that falls off its own end (no `ecall`,
or a truly empty file) crashed with an uncaught `ValueError` and a full
Python traceback instead of a clean CLI error.

**Fix:** `FunctionalSimulator.step()` now catches the decode failure and
re-raises it as `SimulatorTrap`, exactly like the pipeline simulator
already did — the CLI's existing `except SimulatorTrap` handler now
catches this case too.

### 7. Minor — the `demo` subcommand hand-built stale argparse `Namespace` objects

**Symptom:** `silicon demo` crashed with `AttributeError: 'Namespace'
object has no attribute 'max_steps'` partway through, from `cmd_pipeline`
internally needing `args.max_steps` for its `--check` golden-model run.

**Root cause:** `cmd_demo` constructed `argparse.Namespace(...)` objects
by hand for each subcommand it drives, duplicating each subcommand's
argument list outside the real parser — exactly the kind of drift that
was bound to happen the moment a subcommand gained a new attribute
(`--check`'s `max_steps` dependency) that `cmd_demo`'s hand-built copy
didn't know to include.

**Fix:** `cmd_demo` now re-enters through the real `build_parser()` +
`parse_args()` for every step, so it can never again drift out of sync
with a subcommand's actual flags and defaults.

## What was checked and found already correct

- ISA encode → decode round-trips: 470+ randomized cases across every R/I/S/B/U/J
  form, plus the RISC-V spec's real NOP encoding (`0x00000013`) as an
  external sanity anchor.
- `li` pseudo-op across boundary values: `0`, `-1`, `INT32_MAX`,
  `INT32_MIN`, `±2048`, `±4096` — all round-trip through
  assemble → execute → store → read-back correctly.
- `jalr`'s mandatory LSB-clear (`target & ~1`) — directly exercised with
  an odd computed target.
- The cache model's tag/index/offset decomposition and LRU eviction order
  — hand-verified against a worked direct-mapped access sequence
  (`0,16,32,48,0,64,0` → exactly one hit, at the repeated `0`, before the
  aliasing access at `64` evicts it).
- 35/35 program × predictor × cache-config combinations produce
  bit-identical final register file + memory image between the pipeline
  and golden-model simulators (see `tests/test_cross_check.py`).

## Scope note

No required or stretch feature was replaced or dropped. All four required
features (assembler/ISA, golden-model simulator, hazard-aware pipeline,
branch prediction) and both planned stretch features (cache hierarchy,
HTML visualizer + benchmark suite) shipped as originally planned.
