# Ferrule

**An x86-64 assembler, static linker and archiver written from scratch in pure Python — no `as`, no `ld`, no libc in the pipeline.**
It reads real ELF objects (from `gcc -c`, GNU `as`, or its own assembler), resolves symbols, merges and lays out sections, applies relocations, and writes an executable that the Linux kernel runs directly. GNU `as`, `ld`, `ar`, `readelf` and `nm` are used only as *independent oracles* to prove it right.

```
 prog.s ──► ferrule as ──► prog.o ─┐
 gcc -c  ───────────────► main.o ──┼─► ferrule ld ──► ELF executable ──► kernel
 ferrule ar crs lib.a … ► lib.a ───┘      │
                                          ├─ -Map link map      ├─ --report HTML layout view
                                          └─ --gc-sections       └─ crosscheck vs GNU ld
```

## Run it

Python 3.9+ standard library only. (Tests additionally use `gcc`/`binutils` if present and skip cleanly if not.)

```bash
export PYTHONPATH=$PWD                      # run from this folder
python3 -m ferrule as prog.s -o prog.o      # assemble (Intel syntax)
python3 -m ferrule ld crt.o main.o -L. -lfoo -o prog -Map prog.map --report prog.html -v
python3 -m ferrule build prog.s -o prog     # assemble + link in one go
python3 -m ferrule ar crs libfoo.a a.o b.o  # create / append;  ar t|x lib.a
python3 -m ferrule dump prog.o|lib.a|prog   # readelf-style views
python3 -m ferrule nm prog
python3 -m ferrule crosscheck a.o b.o       # link with Ferrule AND GNU ld, run both, compare

./demo.sh      # guided tour of every feature (8 steps)
./verify.sh    # full verification: 69 tests + hostile-input battery + differential fuzz + demo
```

Minimal program:

```asm
.intel_syntax noprefix
.text
.global _start
_start:
    mov eax, 1            # write(1, msg, len)
    mov edi, 1
    lea rsi, [rip + msg]
    mov edx, msg_len
    syscall
    mov eax, 60           # exit(0)
    xor edi, edi
    syscall
.rodata
msg: .ascii "hello\n"
.equ msg_len, . - msg
```

## Features (all shipped)

**Required**
1. **ELF64 relocatable-object reader/writer** — sections, symtab (locals-first, `sh_info`), `.rela.*`, COMDAT groups, NOBITS, special section indices; parses everything gcc emits (`-O0…-O3`, `-g`, `-fPIC/-fPIE`, C++ templates); hardened against corrupt input (6 000 bit-flipped objects, zero crashes).
2. **Static linker** — GNU-ld symbol rules (strong > weak > common, duplicate detection, weak-undefined → 0, `-u`, `-e`), section merging by class/alignment, three page-aligned segments (R-X / R-- / RW- with true NOBITS `memsz>filesz`, W^X, `PT_GNU_STACK`), relocations `64 PC32 PLT32 32 32S 16 8 PC16 PC8 PC64 GOTPCREL GOTPCRELX REX_GOTPCRELX` with range-checked "relocation truncated to fit" diagnostics, synthesised `.got`, `_end/_edata/__bss_start/etext/_GLOBAL_OFFSET_TABLE_`, COMDAT de-duplication, `.symtab` for `nm`/`objdump`.
3. **x86-64 assembler** — Intel syntax; ~110 mnemonic forms (ALU, mov/movabs/movzx/movsx/movsxd, lea, shifts, imul 1/2/3-operand, div/idiv, push/pop, cmovcc/setcc/jcc, string ops + `rep/lock`, bt*/bs*/popcnt, xchg/cmpxchg/xadd, syscall…), every addressing mode (SIB, rip-relative, absolute, `@PLT`, `@GOTPCREL`), REX/high-byte-register rules, jump **relaxation to a fixpoint**, directives (`.section .global .weak .type .size .byte…quad .ascii/.asciz .zero .fill .align/.p2align .equ/.set .comm`), symbol-difference expressions, `.` location counter. **157 forms and 6 000+ random instructions byte-identical to GNU `as`.**
4. **Archives** — GNU `ar` format writer + reader (symbol index, long-name table, odd padding); `ar`/`nm -s`/GNU `ld` accept Ferrule's archives and vice-versa; GNU-ld-style lazy member extraction to a fixpoint (order-sensitive, weak refs don't pull), `-lNAME`/`-L`, `--whole-archive`.

**Stretch (all four delivered)**
5. `--gc-sections` — reachability-based dead-section elimination from the entry point, `.init_array`-style roots, data-pointer reachability.
6. Link **map file** (`-Map`) with archive-pull reasons, per-input-section placement, discarded sections, symbols; plus `dump` / `nm`.
7. Self-contained **HTML layout report** (`--report`) — address-space bar, per-section drill-down, filterable symbol table, light/dark, phone-width safe.
8. **`crosscheck`** — links with Ferrule *and* GNU `ld`, runs both, compares stdout + exit status.

## How it was verified (see [REVIEW.md](REVIEW.md) for 21 bugs found and fixed)
* The kernel runs the output: C programs from gcc (sieve, function-pointer tables, jump tables, statics, commons, weak overrides, recursion, 64-bit division) print identical results and exit codes to GNU-ld builds across `-O0/-O1/-O3/-Os/-fPIE/-fpic/-g/-ffunction-sections + --gc-sections`; C++ COMDAT templates dedupe.
* `readelf -a` accepts every object/executable without warnings.
* Differential fuzzers against GNU `as` (instruction encodings, branch relaxation) and a hostile-input battery (55 malformed programs, truncated/garbled ELF and archives, bit-flip fuzz).

## Known limitations
No TLS, shared objects/dynamic linking, linker scripts, DWARF handling (debug sections are dropped), `.eh_frame_hdr`, or SHF_MERGE string dedupe. SSE/AVX instructions are not assembled (the *linker* handles any compiler output regardless). A bare symbol operand is an immediate address (`mov eax, sym`), unlike gas-Intel's memory load — use `[sym]` for a load. `.align` padding in code uses canonical long NOPs rather than gas's exact choice.

## Why this today
The ledger is full of languages, VMs, engines and emulators, but nothing for the layer *underneath* them all: the thing that turns compiler output into a process image. A linker is a perfect from-scratch project — a precise spec, brutal edge cases (relocation arithmetic, symbol-resolution order, alignment, segments) and, uniquely, **real oracles** (GNU binutils) plus the strictest possible judge: the kernel either runs the file or it doesn't.

## Where a human could take this next
* **Dynamic linking**: `PT_INTERP`/`PT_DYNAMIC`, PLT/GOT lazy binding, `.so` output, linking against libc.so — then `printf` works.
* **Linker scripts** (`SECTIONS { … }`) and custom memory maps for bare-metal/bootloaders.
* **TLS** (`TPOFF32`, `PT_TLS`), `.init_array` execution order, `.eh_frame_hdr` for C++ exceptions.
* **Link-time optimisation of relocations**: `GOTPCRELX` relaxation, identical-code folding, SHF_MERGE string pooling.
* **SSE/AVX encoder** (VEX/EVEX) and AT&T syntax front-end so it can assemble gcc's `-S` output directly — closing the loop with Dominion/Casement-style compilers elsewhere in this repo.
* An **incremental linker** (cache per-object layouts, patch in place) hooked to Mortise.

## Layout
```
ferrule/  elf.py ar.py expr.py x86.py asm.py link.py dump.py report.py cli.py errors.py
tests/    test_elf_ar.py test_asm.py test_link.py test_cli.py  gas_diff.py fuzz_asm.py attack_battery.py
          corpus.s prog1.s  c/{crt.s,algo.c,other.c,rtlib.c,hook.c}
PLAN.md REVIEW.md demo.sh verify.sh
```
