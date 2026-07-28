# Adversarial review

Attacking Cosmac as a hostile reviewer after Phase 2's core build was
"complete and all tests green." Green tests only prove the tests were
satisfiable, not that the code is right — so this pass specifically hunted
for cases the existing tests didn't happen to exercise.

## Bugs found and fixed

### 1. `Chip8.reset()` didn't actually restore the original program

**Found by:** re-reading `reset()` with the question "what if the running
program has written to memory beyond its own bytes by the time reset is
called?"

`reset()` was implemented as "grab whatever's currently in
`memory[0x200:]`, wipe everything, paste it back." That's not the loaded
program — it's *current memory contents*, which a running CHIP-8 program
routinely mutates: `FX55` writes registers to arbitrary memory, sprite data
gets DMA'd around, and self-modifying code is a real, historically-used
CHIP-8 technique. The existing test (`test_reset_keeps_program_clears_state`)
only executed a single `LD` instruction before resetting, so memory was
untouched and the bug never had a chance to show.

**Fix:** `load()` now stashes the exact bytes and origin it was given.
`reset()` reinitializes the machine, then re-pastes *that* saved blob
rather than copying live memory. Added
`test_reset_discards_runtime_writes_beyond_the_original_program`, which
writes garbage past the loaded program and asserts reset scrubs it, plus
`test_reset_before_any_load_is_a_harmless_noop` for the never-loaded case.

### 2. CLI debugger's `break <addr>` silently parsed hex-looking help as decimal

**Found by:** the debugger's own help text says `break 200` and
`break 0x200` are equivalent (both hex); the implementation's
digit-vs-hex-letter heuristic actually parsed `break 200` as **decimal**
200 (= hex `0xC8`) whenever the token had no a-f letters in it. Every
address the debugger ever displays is hex (`0x2A4` in disassembly,
registers, breakpoint lists) — a user typing the exact address they just
read off the screen, without the `0x` prefix, would silently set a
breakpoint at the wrong location with no error.

**Fix:** `_parse_addr` now always parses as hex (`int(token, 16)`, which
already accepts an optional `0x` prefix on its own) — the doc comment
records *why*, since "always hex" looks surprising without the context of
what it's matching. `tests/test_debugger.py` (previously nonexistent — see
finding 4) pins this down explicitly.

### 3. SSE subscriber list was mutated from two threads without a lock

**Found by:** reviewing `server.py` for anything the run-loop thread and
per-connection request-handler threads both touch. `Emulator.subscribers`
was appended to by `/stream` handlers and both appended-to and iterated/
pruned by the background `_run_loop` thread, all without synchronization.
Concurrent connect/disconnect churn (a client refreshing the page while
another frame is broadcasting) could race a `list.remove` against
in-progress iteration.

**Fix:** added a dedicated `subscribers_lock` (deliberately separate from
the CPU's own lock, so a slow client socket write can never block CPU
stepping) guarding every read/mutation of the subscriber list.

### 4. The disassembly panel destroyed its own DOM every animation frame

**Found by:** writing the Playwright breakpoint-click test and watching it
fail with "element was detached from the DOM, retrying" — Playwright was
more honest about this than a human clicking through the UI once would
have been. `renderDisasm` did a full `innerHTML` replace on *every* SSE
frame (60/sec), even when paused and nothing had changed, which meant any
in-progress click on a disassembly line had its target element torn out
from under it mid-click.

**Fix:** `renderDisasm` now computes a cheap signature (PC + visible
addresses + breakpoint set) and skips the rebuild entirely unless it
actually changed. Breakpoint clicking is now reliable; this also stops
wasted DOM churn at 60Hz while paused.

### 5. No dedicated test file for the debugger at all

The CLI debugger (a *required* feature per PLAN.md) had zero automated
tests of its own — it was only exercised indirectly through
`test_ui.py`'s breakpoint/step UI tests, which go through the server's
`Debugger` instance but never touch the CLI REPL, `run_until_stop`'s three
distinct stop reasons, or `_parse_addr` (see finding 2, which a direct
test would have caught immediately). Added `tests/test_debugger.py` (15
tests): breakpoint set/clear, all three `run_until_stop` outcomes
(breakpoint/halted/max_cycles), register/disassembly/memory-dump text
output, and the REPL command loop itself driven with a scripted command
list.

### 6. Assembler silently accepted garbage operands on zero-arg instructions

`CLS extra, junk` and `RET 1, 2` both assembled without complaint, since
the `CLS`/`RET` encoders ignored `ops` entirely. A typo like `RET V0`
(meant to be on the next line) would silently produce a working `RET`
instead of an error.

**Fix:** `CLS`/`RET` now reject any operands. (Left deliberately
un-hardened: instructions where extra operands still name the *correct*
register, e.g. `SKP V0, V1`, just ignore the trailing junk rather than
erroring — a real but much smaller footgun, not worth the complexity
today; noted below as a known limitation.)

### 7. A label could shadow a register or keyword name

`V0: JP V0` or `DT: CLS` parsed as a valid label definition, silently
creating a program where every future reference to `V0`/`DT` is ambiguous
between "the register" and "this address." Nothing downstream ever
noticed — encoding just always preferred the register interpretation, so
the label was silently dead and any jump to it would fail with a
confusing "undefined label" error instead of a clear one at the point of
definition.

**Fix:** label definitions are now checked against both the register
pattern and the keyword set (`I`, `DT`, `ST`, `F`, `B`, `K`) and rejected
immediately with a message naming the actual conflict.

## Things looked at and judged not to be bugs

- **`maze.asm`/`ball.asm`/`pong.asm` end in infinite loops** (`JP halt`,
  etc.) once "done." This is intentional CHIP-8 program structure (there's
  no OS to return to), not a hang — `cpu.halted` specifically means "a
  `Chip8Error` occurred," and stays `False` in all of these; verified by
  the integration tests explicitly asserting `halted` is `False` after
  each program reaches its steady state.
- **`FX0A` requires a fresh key-down event, not just "is some key
  currently held."** If a key was already held before the CPU reached the
  `LD Vx, K` instruction, it does *not* immediately resolve — it waits for
  the next press. This matches how most CHIP-8 interpreters (and test
  suites) implement it and is exercised by `test_fx0a_blocks_until_keypress`
  and the keypad integration test; documented in `cpu.py` rather than
  changed.
- **`JP V0, addr` requires the literal token `V0`, even though `BNNN`'s
  actual runtime register (under the `jump_offset_uses_vx` quirk) is
  determined by the address's own top nibble, not by what you typed.**
  Confirmed by testing both quirk settings directly against the CPU: the
  assembler's `V0` is a readability convention matching how the two-operand
  `JP` form reads in every other CHIP-8 assembler, not an encoding
  parameter — the encoding is correct either way.
- **`ORG` support in the assembler** is implemented but wasn't exercised
  by any shipped program (none of the five `.asm` files need to relocate
  code). Traced through the pass-1/pass-2 address math by hand rather than
  cutting it, since it's needed for `SCRATCH`-style data layout in larger
  programs; a direct test was added in Phase 5's verification pass rather
  than deleting an unused-but-correct feature.

## Fixed but worth flagging as a scope decision

`SKP`/`SKNP`/`SE`/`SNE`/etc. don't reject extra trailing operands the way
`CLS`/`RET` now do — only the two instructions with *zero* expected
operands got that treatment, since those were the ones where a typo could
silently produce a completely different, still-valid instruction. Full
operand-count enforcement across all 33 non-nullary mnemonics is a
mechanical but real chunk of additional work; deferred as lower-value than
the fixes above given the time budget for today's build.
