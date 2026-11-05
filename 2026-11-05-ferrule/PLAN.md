# Ferrule — PLAN

## Concept
Ferrule is a from-scratch **x86-64 assembler + static linker + archiver** in pure Python.
It consumes *real* ELF64 relocatable objects (produced by `gcc -c` or GNU `as`) as well as
objects produced by its own assembler, resolves symbols, merges and lays out sections,
applies relocations, and emits a **statically linked ELF executable that the Linux kernel
runs directly**. No `ld`, no `as`, no libc involved in the pipeline.

## Why it is interesting
Every earlier build in this repo stops at a language, VM, or emulator. The one layer nobody
builds is the one that turns *compiler output into a process image*: the symbol-resolution
rules (strong / weak / common / archive-lazy), section merging, relocation arithmetic
(`S + A - P`), program headers and page alignment. It is also unusually *testable*: GNU
`ld`, `objdump`, `readelf`, `nm` and `ar` act as independent oracles, and the final proof is
that the kernel executes the result and the program prints the right thing.

## Architecture
```
 .s source ──► asm.py ──► ELF .o ─┐
 gcc -c  ───────────────► ELF .o ─┤        ┌─ ar.py (read/write GNU .a, lazy members)
                                  ├─► link.py ──► ELF ET_EXEC  ──► kernel runs it
 libfoo.a ──────────────────────┘        └─ map file / HTML layout report
 elf.py : ELF64 structures, object reader, object writer (shared by all)
 cli.py : `ferrule as | ld | ar | dump | nm | map | report`
```
* `elf.py`   – constants, `ElfObject.parse(bytes)`, `ObjectWriter` (sections, symtab, rela).
* `ar.py`    – GNU/SysV archive reader+writer (symbol index `/`, long-name table `//`).
* `asm.py`   – Intel-syntax assembler: lexer, parser, operand model, instruction encoder
               (REX/ModRM/SIB, imm8/imm32 selection, rip-relative, short-jump relaxation),
               directives, relocation emission.
* `link.py`  – the linker: input loading, archive pull-in fixpoint, symbol table, section
               merge + layout, GOT synthesis, relocation application with overflow checks,
               ELF executable writer, `--gc-sections`, map file.
* `report.py`– self-contained HTML memory-layout visualiser.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | ELF64 relocatable-object **reader and writer** (sections, symtab, rela, strtab round-trip) | **required** |
| 2 | **Static linker**: strong/weak/common/undefined/duplicate symbol rules, section merging by name+flags+alignment, 3-segment layout (RX/R/RW + bss), relocation application (`R_X86_64_64/PC32/PLT32/32/32S/GOTPCREL(X)/PC64`) with range-overflow diagnostics, runnable `ET_EXEC` | **required** |
| 3 | **x86-64 assembler** (Intel syntax, ~60 mnemonics, all addressing modes, directives, relocations, jump relaxation) emitting ELF objects; byte-for-byte checked against GNU `as` | **required** |
| 4 | **Archive (`.a`) support**: GNU `ar` format writer + reader, symbol index, lazy member extraction to a fixpoint, interoperable with `ar`/`nm`/GNU `ld` | **required** |
| 5 | `--gc-sections`: reachability-based dead section elimination from the entry point | stretch |
| 6 | Linker **map file** + `dump`/`nm` inspectors | stretch |
| 7 | Self-contained **HTML layout report** (segments, sections, symbols) | stretch |
| 8 | Differential mode: link with Ferrule *and* GNU `ld`, run both, compare output | stretch |

## Definition of done
* Freestanding C programs compiled by the system `gcc` link with Ferrule and run correctly.
* Pure-assembly programs assembled by Ferrule's assembler link and run.
* Mixed archives / weak overrides / commons behave exactly like GNU `ld`.
* `readelf` accepts every output without warnings.
* A unittest suite plus `demo.sh` exercise every feature and are green.
