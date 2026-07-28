# Cosmac — a CHIP-8 virtual machine, built from scratch

## Concept

[CHIP-8](https://en.wikipedia.org/wiki/CHIP-8) is the interpreted bytecode
language Joseph Weisbecker designed in 1977 for the RCA COSMAC VIP — the
machine this project is named after. It's the classic "hello world" of
emulation: a tiny (35-opcode), fully specified instruction set with a real
display, a real keypad, real timers, and a design simple enough to implement
completely and correctly in a day, yet deep enough to need a real
fetch-decode-execute loop, real bit-level sprite math, and a real toolchain
around it.

No prior build in this ledger has touched CPU emulation. The repo has three
from-scratch bytecode VMs already (Coil's dynamic-language VM, Kiln's WASM
interpreter, PicoSQL's Volcano executor) but none of them emulate a *real,
historical, fixed instruction set* — Cosmac does, and it ships the two
things that make an emulator a *product* rather than a CPU loop: an assembler
so you can write real programs for it, and a debugger so you can see what
those programs are actually doing, cycle by cycle.

## Why this is interesting

- **Verifiable by eye, not just by test.** An emulator is correct when a
  game drawn on its screen actually looks and plays right. That's a much
  stronger, more legible correctness signal than "the loss went down."
- **A complete, closed toolchain.** Source text → assembler → bytecode →
  CPU → disassembler → source text is a full round trip we can prove
  losslessly (assemble, disassemble, reassemble, compare bytes).
- **No dependency on external ROMs.** CHIP-8 ROMs floating around online are
  of unclear provenance/licensing and network access in this sandbox is
  unreliable anyway. Instead, every demo program shipped here is original,
  hand-written in Cosmac's own assembly dialect, so the whole stack —
  assembler included — is exercised by real programs, not just unit tests.
- **A genuinely different verification story.** Every other "from scratch
  X" build in this repo is verified by numbers (gradients, perft counts,
  BM25 scores). Cosmac is verified by *behavior*: single-stepping a program
  and watching register state evolve exactly as the opcode spec says it
  must, and a screen that either does or doesn't show a bouncing ball.

## Architecture

```
cosmac/
  cpu.py          CHIP-8 machine: memory, registers, stack, timers, display,
                   keypad, and the full fetch-decode-execute loop (all 35
                   opcodes)
  assembler.py     mnemonic assembly text -> raw CHIP-8 bytecode
                   (two-pass: label resolution, then encode)
  disassembler.py  raw CHIP-8 bytecode -> mnemonic assembly text
  debugger.py      breakpoints, single-step, run-to-cursor, state
                   inspection, an interactive CLI REPL
  server.py        stdlib http.server + Server-Sent-Events: the *only*
                   place the CPU actually runs; the browser is a dumb
                   terminal (same "engine on the server, browser only
                   renders" pattern as Gambit/Impulse/Formulate)
programs/
  *.asm            original CHIP-8 programs written in Cosmac assembly
                   (pong, maze generator, a bouncing-ball demo, a keypad
                   tester, an opcode self-test ROM)
web/
  index.html       canvas display (64x32 scaled), live register/stack/
                   disassembly panel, memory hex viewer, keypad, and
                   assemble-and-run for arbitrary source
tests/
  test_cpu.py           one test per opcode family against the spec
  test_assembler.py     assemble/disassemble/reassemble round-trip
  test_integration.py   full programs run for N cycles, display checked
  test_ui.py             Playwright smoke test of the live web UI
```

Data flow for the web UI: the browser POSTs "load program" / "key down" /
"key up" / "step" / "run" / "pause" / "set breakpoint" to the server; the
server is the sole owner of a running `Chip8` instance and pushes display
frames + CPU state over an SSE stream. No CHIP-8 logic exists in JavaScript
— the front end is pixels and event plumbing only.

## Feature list

**Required (core, must fully work end-to-end):**

1. **CPU core** — a complete, spec-correct CHIP-8 interpreter: all 35
   opcodes, 4KB memory, 16 general registers + I + PC + SP, a real call
   stack, delay/sound timers ticking at 60Hz independent of CPU speed,
   64×32 monochrome display with correct XOR-sprite-drawing and
   collision-flag (VF) semantics, and a 16-key hex keypad.
2. **Assembler** — a real two-pass assembler translating a documented
   mnemonic syntax (labels, all 35 instructions, `DB`/`DW` data
   directives, comments) into loadable CHIP-8 bytecode.
3. **Disassembler + interactive debugger** — bytecode → mnemonic text
   disassembly, plus a CLI debugger with breakpoints, single-step,
   continue, register/stack/memory inspection, and a live disassembly
   view centered on the program counter.
4. **Browser front end with real programs** — a server-backed interactive
   page that loads and runs original CHIP-8 programs (at least a
   bouncing-ball demo and a two-player Pong), rendering the actual XOR
   display buffer and reading real keyboard input into the CHIP-8 keypad,
   with the CPU running entirely server-side.

**Stretch (implement at least 1):**

5. **Save states** — serialize the full machine (memory, registers,
   timers, display, PC/SP/stack) to a snapshot file and restore it,
   resuming execution bit-for-bit identically to an unsaved run.
6. **Sound** — real audio: while the sound timer is nonzero the browser
   plays an actual tone (Web Audio, driven by the SSE state stream, no
   synthesis logic — just on/off from the server's timer value), and a
   standalone CLI can render a program's beep timeline to a real WAV file
   using a from-scratch square-wave PCM encoder.
7. *(if time allows)* an opcode-level "quirks" toggle (shift/store-load
   quirk variants that real CHIP-8 interpreters disagreed on historically)
   demonstrated by a test program whose behavior visibly differs with the
   toggle on vs. off.

## Verification plan

- Unit tests covering every opcode's documented semantics (arithmetic,
  flags, skips, jumps, sprite XOR + collision) against hand-computed
  expected state.
- Assembler round-trip property test: for every shipped `.asm` program,
  `disassemble(assemble(src))` produces instructions that reassemble to
  byte-identical output.
- Integration tests that load a real program, run it for a fixed number of
  cycles with scripted key input, and assert on resulting display content
  (e.g., the maze demo produces a non-blank, non-trivial pattern; Pong's
  ball position changes frame to frame).
- A Playwright smoke test of the live web UI: load the page, pick a
  program, run it, confirm the canvas is actually being redrawn, and
  confirm the debugger's step/breakpoint controls change visible state.
