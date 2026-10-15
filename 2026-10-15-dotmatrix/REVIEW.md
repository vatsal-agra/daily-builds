# REVIEW — adversarial pass over Dotmatrix (Phase 3)

Method: re-read every file as a hostile reviewer, then attacked the running system — random ROMs, random IO
traffic, garbage input files, nonsense assembler source, and the demo game with scripted button presses. Each
finding below has a repro, a fix and a regression guard.

## Findings

| # | Sev | Finding (what I found) | Repro | Fix | Guard |
|---|-----|------------------------|-------|-----|-------|
| 1 | **High** | `RunFrame` spun forever when a program turned the LCD off: frames were only counted at VBlank, which never comes with the LCD off. `dotmatrix run` / the web loop would hang. | ROM doing `xor a; ldh [rLCDC],a; jr $` then `run -frames 5` → had to be killed (exit 124) | With the LCD off a "frame" still elapses every 70 224 cycles (`gb.go: advance`) | `TestRunFrameWithLCDOff` |
| 2 | Med | Assembler aborted after pass 1, hiding every pass-2 error (range errors, undefined labels); diagnostics were not sorted or de-duplicated, so users fix one error per run. | file with 4 bad lines reported only 1 | Pass 2 always runs; errors are sorted by line and de-duplicated | `TestReportsAllErrors` |
| 3 | Med | Misleading diagnostics: `ld a,(hl)` said *undefined symbol "hl"*; `ld a,[hl` was accepted until pass 2; `bit n,a` with a forward constant said *no form of "bit"*. | see `asm_test.go` `TestErrors` | `badOperandSyntax` (bracket balance, `(hl)` → "use square brackets"), register names in expressions get an explanatory error, constant-operand errors say the value must be known earlier | `TestErrors` (5 new cases) |
| 4 | Med | **Round trip was lossy**: disassembling arbitrary bytes and re-assembling did not reproduce them — `STOP` lost its operand byte, and illegal opcodes were printed as `db $XX`, which the assembler rejected. | random 20 KB blob | `stop $xx` form, illegal opcodes print as `.db $XX`, bare `db`/`dw`/`ds` accepted | `TestRandomBytesRoundTrip` (20 000 random bytes) |
| 5 | Med | Assembler refused code that flows from bank 0 across `$4000` (a perfectly normal flat 32 KiB ROM) with a bogus "past the end of its bank" error. | straight-line code crossing `$4000` | Bank 0 is flat; only `$8000` is a hard limit; overlap detection still applies | `TestRandomBytesRoundTrip` crosses the boundary |
| 6 | Low | Missing common spellings: `ldh [c],a`, `ldh a,[c]`, `jp [hl]`, `ldi`/`ldd`, `db`/`dw`/`ds` without a dot. | — | accepted as aliases | `TestAliases` |
| 7 | Low | CLI silently ran ROMs whose header checksum is wrong (real hardware refuses to boot them). | `run` on a hand-patched ROM | warning on stderr; `info` exits non-zero | manual + `demo.sh` (Phase 5) |
| 8 | Med | **Snake**: on a fatal move the tail had already been erased (and its ring slot consumed) before the collision test, so the dead snake lost a segment on screen. | steer into the wall, look at the death screen | collision is decided first (`is_tail` allows the legal tail-chase), the tail is only erased for a move that happens | `TestSnake*` (Phase 5) |
| 9 | Low | **Snake**: HUD glyphs had no top margin and were clipped against the screen edge. | screenshot | font rows shifted down one pixel | screenshot check |
| 10 | Low | **Test quality**: six of my first-draft hand-computed checks in `cputest.s`/Go tests were *wrong or vacuous* (stale registers after a macro clobbered `A`, an OAM read while the PPU blocks it, a stack-pointer reset inside a subroutine, two "dummy" checks that asserted nothing). In every case the emulator was right and the test was wrong. | — | rewrote them; removed the dummies; the ROM now documents its register-clobber rules | `cputest.s` (60 checks) |
| 11 | Info | Fuzzing: 60 random ROMs × 300 k steps each (with random IO writes, button mashing, all mapper types) and 400 rounds of random VRAM/OAM/LCDC state → **no panics**. | — | — | `TestRandomROMsDoNotPanic`, `TestRandomPPUStateDoesNotPanic` |
| 12 | Info | CLI abuse (junk files, bad addresses, bad flags, unknown buttons, negative frame counts) all give a one-line error and a non-zero exit — no stack traces. | 13 invocations tried | — | `demo.sh` (Phase 5) |

## Known limitations (deliberate, documented — not "fixed")

* **Timing is instruction-granular**: peripherals advance after each instruction, not each memory access, so
  effects that depend on *which M-cycle of an instruction* a register is written (some mooneye tests) are not
  modelled.
* **The PPU renders a scanline at a time**: register changes are seen per line (raster effects work), not per
  pixel. Mode-3 length is `172 + SCX&7 + 6/sprite (+6 window)`, an approximation of the fetcher.
* `STOP` is a 2-byte NOP (no low-power wait); DMG only (no CGB, no double speed).
* Not modelled: OAM-corruption bug, the STAT-write spurious interrupt, LY=153 early-wrap, shortened first line
  after LCD enable, `EI;HALT` return-address quirk, MBC1 multicart wiring, pushes to `$FFFF` via SP.
* Opposite d-pad directions can be pressed together (real hardware can't).
* `parseAddr` in the CLI treats bare numbers as decimal unless they contain a–f (use `0x`/`$` for hex).

## Re-verification (fresh run-through after the fixes)

```
go vet ./... && go test ./...          # all green, includes a regression test per item above
dotmatrix test roms/cputest.s          # PASS 60 checks
repro for #1: ROM that disables the LCD → run -frames 5 returns immediately
repro for #3: asm of a file with (hl)/[hl/bit n → three distinct, accurate diagnostics
repro for #8: snake into the wall → GAME OVER with all three segments still on screen
```
None of items 1–10 reproduce.
