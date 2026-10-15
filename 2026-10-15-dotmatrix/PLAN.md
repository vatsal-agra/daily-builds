# Dotmatrix — PLAN

## Concept
A from-scratch **Game Boy (DMG) emulator in Go** that ships with its **own SM83 assembler and disassembler**,
so every ROM it runs (a self-checking CPU test ROM and a playable game) is authored in this repo — no
copyrighted ROMs, no external fixtures. Core is stdlib-only Go; the same core compiles to WebAssembly for an
in-browser player.

## Why it's interesting
The repo has a RISC-V pipeline sim (Silicon) but no *real hardware emulator*: no timing-coupled CPU/PPU/timer/
interrupt system with undocumented quirks (DAA, half-carry, EI delay, HALT bug, STAT IRQ edges, OAM DMA). Building
the assembler alongside means the emulator is verified by programs we wrote and can inspect end to end.

## Architecture
```
asm/        SM83 assembler (two-pass, labels, directives, expressions) + disassembler
gb/         emulator core: cpu.go (all 245+256 opcodes), bus.go (memory map, DMA), cart.go (header, ROM-only/MBC1/MBC3),
            timer.go, ppu.go (scanline renderer w/ modes + STAT), joypad.go, apu.go (4 channels -> PCM), 
            debug.go (breakpoints, trace, watch)
cmd/dotmatrix/   CLI: asm, dis, run (headless frames -> PNG/WAV), trace, info, serve (web player)
cmd/wasm/        GOOS=js build exposing the core to the browser
roms/       *.s sources: cputest.s (self-checking), snake.s (game), plus tiny feature ROMs
web/        player page (canvas, keyboard, debugger panel)
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **SM83 CPU** — all official opcodes + CB prefix, exact flag behaviour (DAA, ADC/SBC half-carry, ADD SP,e, LD HL,SP+e), interrupts, EI delay, HALT (+bug), per-instruction cycle counts | **required** |
| 2 | **Bus, cartridge & peripherals** — memory map, echo RAM, header parse + checksum, ROM-only/MBC1/MBC3 banking + RAM, OAM DMA, DIV/TIMA timer with falling-edge quirk, joypad, serial output | **required** |
| 3 | **PPU** — mode 2/3/0/1 timing, BG/window/sprite rendering (priority, flips, 8x16, 10/line limit), palettes, LY/LYC + STAT interrupts, VBlank; framebuffer → PNG | **required** |
| 4 | **SM83 assembler + disassembler** — labels, `.org/.db/.dw/.ds/.incbin-less`, expressions, local labels, header/checksum fixup, round-trip with disassembler | **required** |
| 5 | **Debugger / tracer** — breakpoints, watchpoints, instruction trace log, register dump, single-step CLI | stretch |
| 6 | **APU** — 2 pulse + wave + noise channels mixed to 16-bit PCM, WAV export | stretch |
| 7 | **Web player** — Go→WASM core, canvas, keyboard, on-page debugger | stretch |
| 8 | Save states (serialise/restore whole machine) | stretch |

Required: 1–4. Stretch: 5–8 (aim for at least 5, 6, 7).

## Verification strategy
- Go unit tests per opcode group against hand-computed truth tables (flags exhaustively for ALU ops over all 8-bit operands).
- `cputest.s` self-checking ROM run headless: result reported via serial + screen.
- PPU golden checks (pixel assertions from assembled ROMs), timer/interrupt timing tests, MBC bank-switch ROM.
- Assembler↔disassembler round trip over all 501 opcodes.
- Playwright check of the web player.
