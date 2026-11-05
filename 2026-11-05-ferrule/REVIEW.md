# REVIEW — adversarial pass on Ferrule

Method: I switched sides and tried to break my own work with (a) a randomised differential fuzzer against GNU `as`
(`tests/fuzz_asm.py`, 6 000+ random instructions plus random label/jump programs for relaxation),
(b) a hostile-input battery (`tests/attack_battery.py`: 55 malformed assembly programs, truncated/garbled ELF and
`.a` files, 6 000 bit-flipped real gcc objects fed through parse+link), (c) real compiler output linked by Ferrule and
GNU `ld` and compared at run time (`tests/c/`, 11 gcc flag sets × with/without a weak-override object), (d) CLI abuse.

## Findings (all fixed)

| # | Sev | Finding | Found by | Fix |
|---|-----|---------|----------|-----|
| 1 | **High** | **`ah/ch/dh/bh` encoded as `al/cl/dl/bl`** — `mov ah, 5` silently assembled to `mov al, 5` (high-byte regs numbered 0-3 instead of 4-7). Silent miscompile. | gas corpus diff | Register numbers 4-7, REX conflict check kept |
| 2 | **High** | Immediates were not normalised by operand width: `add dword ptr [m], 0xFFFFFFFF` emitted imm32 where the value is -1 (gas: imm8 `83 /0 ff`), and out-of-range values (`mov al, 300`, `add eax, 1<<32`) were accepted/truncated. | fuzz | `norm_imm()` validates range per width and picks imm8 on the *signed* interpretation |
| 3 | **High** | `--gc-sections` **crashed** ("refers to discarded section") on a real `-ffunction-sections` build because the result-building loop asked for the address of symbols living in collected sections. | real gcc matrix | Collected symbols skipped in result/symtab |
| 4 | Med | Mismatched operand sizes silently accepted: `cmov`, `bsf/bsr/popcnt`, 2-/3-operand `imul`, `xchg` (`cmovg r9, r9d` encoded). | fuzz | Explicit size-equality checks |
| 5 | Med | `[rcx*1+d]` rewritten into base form (valid but not the encoding gas/users ask for). | fuzz | Only `[rsp*1]` is promoted to a base |
| 6 | Med | `xchg r64,r64` put operands in the wrong ModRM fields; 16-bit accumulator short form missed. | fuzz | Fixed order, allow `66 90+r` |
| 7 | Med | Prefix order wrong for `popcnt r16`, `rep movsw` (`F3 66` vs `66 F3`). | fuzz | `0x66` always first, lock/rep inserted after it |
| 8 | **High** | **Parser/linker crashed on corrupt objects**: 8/300 random bit-flips raised `MemoryError`/`IndexError` (NOBITS section of ~2^60 bytes, bad string-table / section indices). | bit-flip battery | Section/symbol index validation, size and alignment sanity limits, parse wrapper converting low-level errors to `FerruleError`; 6 000 mutations now: 0 crashes |
| 9 | Med | `.zero 1<<40` → `MemoryError`. | battery | 256 MiB block cap, `.p2align` range check |
| 10 | Med | `.equ Y, label+4` silently produced a bogus *undefined* symbol `Y`. | battery | Alias expansion before layout; global alias is a clear error; circular `.equ` detected |
| 11 | Med | `--base 0x400123` accepted → kernel would refuse the ELF; `--base abc` gave a Python traceback. | battery / CLI | Page-alignment check, friendly message |
| 12 | Med | `ar crs` on an existing archive **overwrote** it (real `ar c` only suppresses the create warning); `ar t missing.a` printed a traceback. | CLI | Existing members preserved/replaced by name; `OSError` handled globally |
| 13 | Med | `-lNAME` swallowed by argparse, options after positionals rejected, so `ld a.o -L. -lfoo b.o` was impossible. | CLI | Hand-written `ld` option parser preserving command-line order (archive order matters) |
| 14 | Low | GOT bookkeeping smuggled pseudo-symbols (`"\0obj\0id"`) into the global table → leaked into `res.symbols`/map. | code read | Dedicated local-key table |
| 15 | Low | `[rip + 0x20]` (literal displacement) rejected. | gas corpus | Treated as a raw disp32 like gas |
| 16 | Low | Map file listed hundreds of zero-byte discarded sections. | gc map | Zero-size sections not reported |
| 17 | Low | `.fill` unsupported. | battery | Implemented (count, size 1-8, value) |

## Known limitations (documented rather than bugs)
* A bare symbol in an operand is an **immediate address** (NASM-like); GNU `as -msyntax=intel` treats `mov eax, sym` as a *memory load*. Use `[sym]` for a load, `offset sym` (also accepted) or bare `sym` for the address.
* Alignment padding in code uses 1–9-byte canonical NOPs; gas picks different (equivalent) multi-byte NOPs, so `.align` in `.text` is not byte-identical to gas.
* `mov eax, sym` uses `R_X86_64_32`; gas uses `R_X86_64_32S`. Both link identically.
* No TLS, no shared objects/dynamic linking, no linker scripts, no SHF_MERGE string de-duplication (strings are concatenated — correct but not minimal), no `.eh_frame_hdr`.

## Fresh run-through after the fixes
* `tests/gas_diff.py tests/corpus.s` → 0 mismatches of 157 forms.
* `tests/fuzz_asm.py` seeds 1-6 × 1 000 instructions → 0 mismatches, 0 wrongly-accepted, 0 wrongly-rejected; 150 random relaxation programs per seed → 0 mismatches.
* `tests/attack_battery.py` → 0 crashes (every failure is a one-line `FerruleError` with file/line).
* gcc matrix (`-O0/-O1/-O2/-O3/-Os/-fPIE/-fpic/-g/-ffunction-sections/-fno-common/-fcf-protection=none`) → Ferrule and GNU `ld` executables produce identical stdout and exit codes; `--gc-sections` build runs correctly.
* C++ COMDAT groups (templates / inline functions in two TUs) dedupe correctly (28 = 28 vs GNU ld).

## Phase 5 findings (found *by the test-suite and demo*, all fixed)

| # | Sev | Finding | Found by | Fix |
|---|-----|---------|----------|-----|
| 18 | **High** | `.` (location counter) was evaluated lazily at *use* time: `.equ msg_len, . - msg` failed outright, and `.size f, .-f` recorded the distance to the **end of the section** — wrong whenever more code followed (exactly the pattern gcc emits after every function). | `demo.sh` | `.` is pinned to a hidden local label at the directive; same-section label differences fold to constants wherever they are used |
| 19 | **High** | `-u SYM` was applied *after* archives had already been scanned, so it could never pull a member (GNU ld applies it first). | `test_whole_archive_and_undefined_flag` | `-u` seeds the undefined set at construction |
| 20 | Med | An in-memory `Archive` built by assigning `.members` had an empty symbol index, so nothing was ever pulled from it. | `test_only_needed_members_are_pulled_transitively` | `Archive.index` is now a lazily (re)built property |
| 21 | Low | Demo text claimed a weak reference pulls `hook.o`; actually (correctly, as in GNU ld) it doesn't. The demo now shows both behaviours (`-u optional_hook` to force it). | reading demo output | demo rewritten |
