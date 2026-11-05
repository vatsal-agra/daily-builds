# Ferrule

An x86-64 **assembler + static linker + archiver** in pure Python. Takes real ELF objects (from `gcc -c`, GNU `as`, or Ferrule's own assembler) and produces executables the Linux kernel runs directly.

**Status: Phase 2 (core build) complete.** Plan: [PLAN.md](PLAN.md).

## Working so far (the 4 required features)
1. **ELF64 object reader/writer** (`ferrule/elf.py`) — parses gcc output; round-trips; `readelf` accepts what it writes.
2. **Static linker** (`ferrule/link.py`) — symbol rules (strong/weak/common), section merging, 3-segment layout, `PC32/PLT32/32/32S/64/PC64/GOTPCREL(X)` relocations with range checks, `_end`/`_edata`/`_GLOBAL_OFFSET_TABLE_` etc.
3. **Assembler** (`ferrule/asm.py`, `x86.py`) — Intel syntax, 157 instruction forms byte-identical to GNU `as`, jump relaxation, directives, relocations.
4. **Archives** (`ferrule/ar.py`) — GNU `ar` format read/write with symbol index; lazy member extraction like `ld`.

```
python3 -m ferrule as prog.s -o prog.o
python3 -m ferrule ld start.o main.o libfoo.a -o prog -Map prog.map
```
