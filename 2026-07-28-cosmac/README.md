# Cosmac

A CHIP-8 virtual machine built entirely from scratch: a spec-accurate CPU
emulator, its own two-pass assembler and disassembler, an interactive
debugger (a CLI REPL and a server-backed browser front end sharing the same
underlying objects), five original CHIP-8 programs written in Cosmac's own
assembly dialect, and a from-scratch WAV encoder that renders a program's
real sound-timer activity to audio.

Named for the RCA COSMAC VIP, the 1977 machine CHIP-8 was designed for.

![Cosmac running Pong, live in the browser](docs/screenshot.png)

## Why this, today

This repo has built five CDCL SAT solvers, four Monte Carlo path tracers,
three from-scratch full-text search engines, and — as of yesterday — seven
separate GPT-style transformers ("Loom"). CPU emulation had never been
touched. It's the classic on-ramp into emulation for a reason: a small
(35-opcode), fully and unambiguously specified instruction set, deep enough
to demand a real fetch-decode-execute loop and real bit-level sprite math,
but scoped enough to implement *completely and correctly* — not a fragment
of a bigger, messier ISA — in one day.

It also offers a verification story none of this repo's other builds have:
correctness you can watch. A ray tracer is "close enough" until you check
pixel values against a formula. An emulator is right when Pong's ball
actually bounces off a paddle that's actually where you put it, or wrong in
a way that's immediately, visibly, un-arguably wrong. See
[PLAN.md](PLAN.md) for the full design rationale.

## Quick start

```bash
cd 2026-07-28-cosmac
python3 -m cosmac.server        # http://127.0.0.1:8880 -- Pong, maze, etc. live in the browser
```

Or drive a program from the terminal debugger instead:

```bash
python3 -m cosmac.debugger programs/pong.asm
cosmac> break 20A
cosmac> run
cosmac> regs
```

Or render a program's sound-timer activity to a real, playable WAV file:

```bash
python3 -m cosmac.wav programs/beep.asm out.wav
```

## Run the tests

```bash
python3 -m unittest discover -s tests   # 123 tests
python3 demo.py                          # standalone end-to-end walkthrough, no test framework
```

`tests/test_ui.py` needs `pip install playwright`; everything else
(including `demo.py`) is stdlib-only.

## Feature list

**Required:**

1. **CPU core** (`cosmac/cpu.py`) — all 35 CHIP-8 opcodes, 4KB memory, 16
   registers + I + PC + a real call stack, 60Hz delay/sound timers
   independent of CPU speed, a 64×32 XOR-drawn display with correct
   collision (`VF`) semantics, a 16-key hex keypad, and three configurable
   "quirks" (shift/store-load/jump variants real interpreters historically
   disagreed on — toggleable live in the browser UI).
2. **Assembler** (`cosmac/assembler.py`) — a real two-pass assembler:
   labels (forward and backward), all 35 instructions, `DB`/`DW`/`ORG`
   directives, string literals, and error messages that name the exact
   line and problem.
3. **Disassembler + interactive debugger** (`cosmac/disassembler.py`,
   `cosmac/debugger.py`) — bytecode → mnemonic text with a proven-lossless
   round trip back through the assembler, plus breakpoints, single-step,
   run-to-breakpoint, and register/stack/memory/disassembly inspection,
   in both a CLI REPL and the browser.
4. **Browser front end with real programs** (`cosmac/server.py`,
   `web/index.html`) — the CPU runs only on the server, in a background
   thread; the browser is a thin renderer driven by Server-Sent Events
   (the same architecture as this repo's Gambit/Impulse/Formulate builds).
   Runs `ball.asm`, `maze.asm`, `keypad.asm`, and a real two-player
   `pong.asm`, with live registers, clickable-to-toggle breakpoints on a
   live disassembly, and a memory viewer centered on `I`.

**Stretch (all three shipped):**

5. **Save states** — the full machine (memory, registers, timers,
   display, stack) round-trips through `snapshot()`/`restore()` and the
   browser's save/load buttons, verified to resume execution identically
   to an unsaved run.
6. **Real audio** — `cosmac/wav.py` runs the actual CPU, records the real
   `sound_timer` state at every 60Hz tick, and hand-writes a genuine
   16-bit PCM `.wav` (RIFF header included, no `wave` module) — verified
   independently by decoding it back with Python's stdlib `wave` reader.
   The browser plays a live Web Audio beep off the same signal.
7. **Quirks toggle** — `Quirks.shift_uses_vy`,
   `load_store_increments_i`, and `jump_offset_uses_vx` are live UI
   checkboxes, each backed by a direct unit test proving the CPU actually
   behaves differently with the toggle on vs. off (`test_shr_legacy_uses_vy`
   vs. `test_shr_modern_uses_vx`).

## What's in `programs/`

All five are original, written for this build in Cosmac's own assembly:

- `ball.asm` — a ball bouncing off all four walls.
- `maze.asm` — the classic "diagonal-tile maze" generator, generalized to
  a readable raster loop.
- `keypad.asm` — draws the hex digit of whichever key you last pressed.
- `pong.asm` — a real two-player Pong (key `1`/`4` and `C`/`D`), with
  paddle-collision detection built from the SUB/VF "compare" idiom CHIP-8
  programs use in place of a missing less-than instruction, and a live
  scoreboard.
- `selftest.asm` — an opcode self-test ROM exercising arithmetic flags,
  BCD conversion, register store/load, and skip instructions through the
  real assembler → bytecode → CPU pipeline (not just direct Python calls).
- `beep.asm` — four timed beeps, written to give `cosmac/wav.py` and the
  browser's Web Audio beep something real to render.

## Adversarial review

[REVIEW.md](REVIEW.md) documents the Phase 3 hostile-reviewer pass: 7 real
bugs found and fixed, including a `reset()` that silently restored
*current* memory contents instead of the originally loaded program, a CLI
debugger bug where `break 200` silently meant decimal 200 instead of the
hex `0x200` its own help text promised, a threading race in the SSE
broadcaster, and a UI bug where the disassembly panel rebuilt its entire
DOM 60 times a second, breaking in-flight breakpoint clicks.

## Where a human could take this next

- **Real ROM compatibility.** Cosmac never loads third-party ROMs (their
  licensing is murky and this sandbox had unreliable network access), so
  it's never been checked against the wide "zoo" of real historical CHIP-8
  software or community opcode test ROMs (e.g. Timendus' test suite) —
  only against its own hand-written test programs and self-test ROM.
- **SUPER-CHIP / XO-CHIP.** The 1990s 128×64 high-res extension and later
  XO-CHIP (extra planes, more opcodes) are natural, well-specified
  extensions of exactly this codebase.
- **A visual/step-through assembler debugger**: syntax highlighting, a
  source map so the browser's live disassembly view can show the original
  `.asm` source line instead of decoded mnemonics.
- **Cycle-accurate speed profiles** modeling real historical interpreters
  (the original COSMAC VIP ran meaningfully slower than the ~500-800Hz
  "feels right" most modern CHIP-8 programs assume).
- **Multiplayer over the network** — Pong's server-authoritative
  architecture (the CPU already lives only on the server) is most of the
  way to letting two physically separate browsers each control one
  paddle.
