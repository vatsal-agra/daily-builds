# Dotmatrix

A from-scratch **Game Boy (DMG) emulator** written in Go, shipped together with its own **SM83 assembler and
disassembler** — so every ROM it runs (a 60-check CPU test suite, an MBC1 battery-save test, and a complete
Snake game with sound) is written in this repo. Standard library only; no external ROMs, no dependencies.
The same core compiles to WebAssembly for an in-browser player with a live assembler IDE.

```
 ┌─ asm/ ──────────────┐   ┌─ gb/ ────────────────────────────────────┐   ┌─ cmd/ & web/ ──────────────┐
 │ SM83 assembler       │   │ CPU · bus · cart/MBC1/3/5 · timer · DMA │   │ CLI: asm dis info run test │
 │ + disassembler       │──▶│ PPU · joypad · serial · APU · debugger  │──▶│ trace debug serve          │
 │ (one opcode table)   │   │ save states                             │   │ Go→WASM browser player     │
 └──────────────────────┘   └──────────────────────────────────────────┘   └────────────────────────────┘
```

## Run it

```sh
go build -o dotmatrix ./cmd/dotmatrix

./dotmatrix serve                          # browser player + assembler IDE → http://127.0.0.1:8080
./dotmatrix run roms/snake.asm -frames 400 -keys "5:start,6:-start,60:down" -png shot.png -wav sound.wav
./dotmatrix test roms/cputest.asm          # self-checking CPU ROM → "PASS 60 checks"
./dotmatrix test roms/mbc1test.asm         # MBC1 banking + battery RAM → "PASS"
./dotmatrix asm roms/snake.asm -o snake.gb -sym snake.sym
./dotmatrix info snake.gb                  # header + checksum validation
./dotmatrix dis snake.gb -from 0x150 -len 32
./dotmatrix debug roms/snake.asm           # interactive debugger ('help' inside)
./dotmatrix trace roms/cputest.asm -n 30   # bgb-style instruction trace

./verify/verify.sh                         # 36 end-to-end checks (build, vet, tests, every CLI command, abuse cases, browser)
MUTANTS=1 ./verify/verify.sh               # …plus mutation testing: 49 injected bugs, all must be caught
go test ./...
```

Controls in the browser: arrows, **X** = A, **Z** = B, **Enter** = Start, **Backspace** = Select, **F10** = step
one instruction, **Ctrl+Enter** in the editor = assemble & run. Touch pad on phones. Sources can be edited live;
assembler errors are listed with clickable line numbers.

`.gb` files from elsewhere work too (`run game.gb`, *Open .gb ROM…* in the browser) — DMG cartridges of type
ROM-only, MBC1, MBC3 (+RTC) and MBC5.

## Features

**Core (required)**
1. **SM83 CPU** — all 244 base + 256 CB-prefixed opcodes with exact flag behaviour (DAA, ADC/SBC half-carry,
   `ADD SP,e`, `LD HL,SP+e`), interrupts with priority and 5-M-cycle dispatch, EI delay, HALT and the HALT bug,
   per-instruction cycle counts, illegal-opcode lock-up. ALU/CB/DAA verified *exhaustively* against independent references.
2. **Bus, cartridge and peripherals** — full memory map with echo RAM, header parsing and checksum validation,
   ROM-only/MBC1 (modes, 0→1 quirk, large ROMs)/MBC3 (RTC)/MBC5, battery RAM, timed OAM DMA with CPU bus
   blocking, DIV/TIMA/TMA/TAC with the falling-edge quirk and delayed reload, joypad matrix + interrupt, serial port.
3. **PPU** — mode 2/3/0/1 timing, LY/LYC/STAT interrupts with STAT-line blocking, BG, window (own line
   counter), sprites (8×8/8×16, flips, palettes, DMG X-priority, BG-priority bit, 10 per line), VRAM/OAM access
   blocking, LCD off/on; PNG, RGBA and ASCII output. Raster effects work (registers are sampled per line).
4. **SM83 assembler + disassembler** — two-pass, forward references, local labels, expressions
   (`+ - * / % << >> & | ^ ~`, `low()`/`high()`), macros with arguments and unique labels, `.rept`, `.include`,
   `.org/.bank/.db/.dw/.ds/.equ`, RAM labels, automatic header + checksum fix-up, symbol files, accurate multi-error
   diagnostics. One generated opcode table drives both directions: random bytes disassemble and re-assemble losslessly.

**Stretch (all shipped)**

5. **Debugger** — breakpoints (with conditions like `a==0x50 && [0xC000]!=0`), read/write watchpoints,
   step / step-over / finish / until, execution history, memory dump, disassembly with labels, register and RAM
   editing, PPU/IO views. Scriptable from stdin.
6. **APU** — two pulse channels (duty, envelope, length, frequency sweep with overflow), wave channel, noise
   (15/7-bit LFSR), frame sequencer, NR50/51/52 panning and power behaviour, 44.1 kHz stereo with 4× oversampling
   and a DC-blocking filter; **WAV export**. Real-time in the browser via WebAudio.
7. **Browser player** — Go→WASM core (1.1 MB gzipped), canvas screen, on-screen pad, audio, **live assembler IDE**,
   CPU/disassembly/memory/tile-viewer/serial panes, click-to-set breakpoints, quick-save slot, state download/upload.
8. **Save states** — whole-machine, deterministic, versioned and cartridge-checked; a rejected file never
   half-applies. Available in the CLI, debugger and browser.

**Demo ROMs (`roms/`)** — `cputest.asm` (60 hand-computed checks run *inside* the emulator), `mbc1test.asm`
(banks + battery persistence), `snake.asm` (title, play, speed-up, win/lose, restart, sound effects — 800 lines of SM83).

## How it is verified

* **98 Go test functions** (asm, gb, CLI) — exhaustive ALU/CB/DAA/16-bit tables, cycle counts, interrupts/HALT/EI,
  timer, DMA, joypad, PPU timing and rendering, MBC banking + RTC, APU frequency/duty/envelope/length/sweep/wave/noise,
  save states, debugger, fuzzing (random ROMs and random PPU/IO state never panic).
* **The ROMs test the emulator from inside**, and a **bot plays Snake** through the emulated joypad, reading the
  game's own variables via the assembler's symbol table.
* **Mutation testing** (`verify/mutants.py`): 49 plausible bugs injected one at a time into the CPU, timer, bus,
  PPU, cartridge, APU, assembler, debugger and save-state code — all 49 are caught. (Writing it exposed a
  weak test — a symmetric sprite tile that made X-flip invisible — which is now fixed.)
* **Playwright** drives the browser player: load, play, steer, breakpoints, assembler errors, custom program,
  `cputest` PASS, save/load, bad ROM, phone layout, zero console errors.
* [REVIEW.md](REVIEW.md) documents the adversarial pass: 12 findings (one hang, lossy round trip, misleading
  diagnostics, a game bug…), each fixed with a regression guard, plus the known limitations.

## Design notes

* **Timing model**: the CPU runs whole instructions; peripherals advance afterwards by the instruction's M-cycles
  (timer/DMA/serial in 4-cycle slices). The PPU is scanline-accurate with variable mode-3 length. This passes the
  suites above and runs ~2,200 fps natively but cannot reproduce mid-instruction effects (see limitations).
* **Single opcode table** (`asm/table.go`): the assembler matches operands against it and the disassembler decodes
  from it, so the two cannot drift apart — the 500-opcode round trip is a test.
* **Save-state codec** walks structs by reflection and skips tagged fields, so new state is saved automatically.
* The browser serves the WASM core gzipped from inside the Go binary (`web/embed.go`); `web/build.sh` rebuilds it.

## Limitations (honest)

DMG only (no CGB colour/double-speed); `STOP` is a NOP; instruction-granular timing and per-scanline rendering
(no mid-line effects, OAM-corruption bug, STAT-write quirk, LY=153 early wrap); MBC2 / MBC6 / MBC7 / HuC and the
Pocket Camera are rejected; the APU omits obscure length-counter/trigger edge cases; no link-cable peer.
No commercial ROMs were available offline, so compatibility with real cartridges is *argued* (by the tests above)
rather than demonstrated — passing Blargg/Mooneye suites is the obvious next proof.

## Why I chose this today

The repo has a RISC-V pipeline simulator, a TCP stack, a filesystem, a WebAssembly toolchain — but no *hardware
emulator*: nothing where a CPU, video chip, timers, interrupts, DMA and sound all have to agree on the clock, and
where half the correctness lives in undocumented quirks. A Game Boy is the smallest machine that has all of
that, and writing the assembler alongside it removed the usual blocker (no ROMs offline) while making every
claim inspectable: the emulator is tested by programs I can read, and the assembler is tested by running them.

## Where a human could take this next

1. **Run the community test ROMs** (Blargg `cpu_instrs`/`instr_timing`, Mooneye acceptance, dmg-acid2) — the
   debugger and `-until-serial` already make triage easy. Expect to move to per-M-cycle memory access to pass the timing suites.
2. **Pixel-FIFO PPU** for true mode-3 timing, mid-scanline writes and sprite-fetch penalties.
3. **Game Boy Color**: banked VRAM/WRAM, palettes, HDMA, double speed.
4. **Link cable**: two machines over a socket (the serial plumbing is already event-driven) → Tetris versus.
5. **Rewind / TAS tools**: save states are cheap (64 KiB) and deterministic — a ring buffer gives rewind; input
   scripts (`-keys`) already give replays.
6. **Assembler niceties**: `.if/.else`, `.section` with a linker-style bank allocator, listing files, source-level
   stepping in the debugger (the assembler already records an address→line map).
7. **Audio accuracy** (length-clock quirks, high-pass filter modelling) and a WebAudio worklet for lower latency.
