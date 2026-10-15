# Dotmatrix

A from-scratch **Game Boy (DMG) emulator** in Go, shipped with its own **SM83 assembler and disassembler** —
so every ROM it runs is written in this repo. No external ROMs, no dependencies (stdlib only).

> **Status: Phase 3 complete (adversarial review).** Required features 1–4 work end to end; see [REVIEW.md](REVIEW.md) for what the review found and fixed. See [PLAN.md](PLAN.md).

## Quick start

```sh
go build -o dotmatrix ./cmd/dotmatrix
./dotmatrix test roms/cputest.s                         # self-checking CPU test ROM → "PASS 60 checks"
./dotmatrix run roms/snake.s -frames 120 -keys "10:start,12:-start,60:down" -png out.png
./dotmatrix asm roms/snake.s -o snake.gb && ./dotmatrix info snake.gb
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
| Demo ROMs | `roms/cputest.s`, `roms/snake.s` | done |

More (debugger, APU, web player, docs) arrives in the next phases.
