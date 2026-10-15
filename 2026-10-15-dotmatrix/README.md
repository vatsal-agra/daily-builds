# Dotmatrix

A from-scratch **Game Boy (DMG) emulator** in Go, shipped with its own **SM83 assembler and disassembler** —
so every ROM it runs is written in this repo. No external ROMs, no dependencies (stdlib only).

> **Status: Phase 5 complete (verification).** `verify/verify.sh` runs 36 end-to-end checks green; `MUTANTS=1` adds 49-mutant mutation testing (49/49 killed). See [PLAN.md](PLAN.md) and [REVIEW.md](REVIEW.md).

## Quick start

```sh
go build -o dotmatrix ./cmd/dotmatrix
./dotmatrix test roms/cputest.asm                         # self-checking CPU test ROM → "PASS 60 checks"
./dotmatrix serve                                        # browser player + assembler IDE on http://127.0.0.1:8080
./dotmatrix debug roms/snake.asm                         # interactive debugger
./dotmatrix run roms/snake.asm -frames 120 -keys "10:start,12:-start,60:down" -png out.png
./dotmatrix asm roms/snake.asm -o snake.gb && ./dotmatrix info snake.gb
./dotmatrix dis snake.gb -from 0x150 -len 32
go test ./...
```

## What exists so far

| Feature | Where | State |
|---|---|---|
| SM83 CPU (all 244 base + 256 CB opcodes, interrupts, EI delay, HALT bug, cycle counts) | `gb/cpu.go` | done, exhaustively tested |
| Bus, cartridge (ROM-only / MBC1 / MBC3+RTC / MBC5), OAM DMA, timer, joypad, serial | `gb/bus.go` `gb/cart.go` `gb/timer.go` `gb/joypad.go` | done |
| PPU (modes, STAT, BG/window/sprites, 8x16, priority, 10/line) → PNG | `gb/ppu.go` `gb/render.go` `gb/image.go` | done |
| SM83 assembler + disassembler (labels, macros, `.rept`, `.include`, banks, header fixup) | `asm/` | done, 500-opcode round trip |
| Demo ROMs | `roms/cputest.asm`, `roms/snake.asm` | done |

| **Stretch:** interactive debugger (breakpoints with conditions, read/write watchpoints, step/next/finish, history, symbols) | `gb/debug.go` `cmd/dotmatrix/debug.go` | done |
| **Stretch:** 4-channel APU (2 pulse + sweep, wave, noise, envelopes, length counters, panning) → 44.1 kHz stereo, WAV export | `gb/apu.go` | done, 15 tests |
| **Stretch:** save states (whole machine, deterministic, validated) | `gb/state.go` | done |
| **Stretch:** browser player — Go→WASM core, live assembler IDE, debugger/tile/memory panes, touch pad, audio | `cmd/wasm` `web/` | done |

Run the browser player with `dotmatrix serve` (the wasm core is stored gzipped in `web/`; rebuild with `web/build.sh`).

Final docs arrive in Phase 6.
