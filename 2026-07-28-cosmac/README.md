# Cosmac

A CHIP-8 virtual machine built entirely from scratch — CPU emulator, its own
two-pass assembler and disassembler, an interactive debugger (CLI + a
server-backed browser front end), and five original CHIP-8 programs written
in Cosmac's own assembly dialect. See [PLAN.md](PLAN.md) for the full design
rationale.

**Status: Phase 2 (core build) complete.** All four required features work
end-to-end: CPU core, assembler, disassembler + debugger, and a live browser
UI running real programs. 83 tests pass (unit, assembler round-trip,
integration, Playwright UI smoke tests).

## Quick start

```
cd 2026-07-28-cosmac
python3 -m cosmac.server        # http://127.0.0.1:8880
```

Or drive a program from the terminal debugger:

```
python3 -m cosmac.debugger programs/pong.asm
```

## Run the tests

```
python3 -m unittest discover -s tests
```

(`test_ui.py` needs `pip install playwright`; the other three suites are
stdlib-only.)

## What's implemented so far

- `cosmac/cpu.py` — full 35-opcode CHIP-8 interpreter, configurable quirks
  (shift/store-load/jump variants that real interpreters disagreed on),
  save/restore state.
- `cosmac/assembler.py` — two-pass mnemonic assembler (labels, `DB`/`DW`,
  string literals).
- `cosmac/disassembler.py` — bytecode → mnemonic text, lossless round-trip
  with the assembler.
- `cosmac/debugger.py` — breakpoints, step/run, register/memory/disasm
  inspection, a CLI REPL.
- `cosmac/server.py` + `web/index.html` — the CPU runs server-side in a
  background thread; the browser is a thin renderer driven by
  Server-Sent Events (same architecture as this repo's Gambit/Impulse
  builds).
- `programs/` — `ball.asm`, `maze.asm`, `keypad.asm`, `pong.asm`,
  `selftest.asm`, all original, all exercised by the test suite.

Remaining phases (adversarial review, stretch features, polish, final
verification) are next.
