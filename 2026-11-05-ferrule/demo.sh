#!/usr/bin/env bash
# Ferrule demo: exercises every feature end to end and prints what it proves.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD"
F="python3 -m ferrule"
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
hr() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

hr "1. assemble Intel-syntax source to an ELF object, link it, run it in the kernel"
$F as tests/c/crt.s -o "$W/crt.o"
cat > "$W/hello.s" <<'ASM'
.intel_syntax noprefix
.text
.global _start
_start:
    mov eax, 1              # write(1, msg, len)
    mov edi, 1
    lea rsi, [rip + msg]
    mov edx, msg_len
    syscall
    mov eax, 60             # exit(5)
    mov edi, 5
    syscall
.rodata
msg: .ascii "hello from a Ferrule-linked executable\n"
.equ msg_len, . - msg
ASM
$F build "$W/hello.s" -o "$W/hello" -v
"$W/hello" || echo "(exit status $? -- expected 5)"

hr "2. compile real C with gcc, link with Ferrule (asm startup + C + archive), compare with GNU ld"
CF="-O2 -ffreestanding -fno-pic -fno-pie -fno-stack-protector -fno-asynchronous-unwind-tables -fcommon -ffunction-sections -c"
for f in algo other rtlib hook; do gcc $CF tests/c/$f.c -o "$W/$f.o"; done
$F ar crs "$W/librt.a" "$W/rtlib.o" "$W/other.o" "$W/hook.o"
$F ar t "$W/librt.a"
$F ld "$W/crt.o" "$W/algo.o" "$W/librt.a" -o "$W/algo" -Map "$W/algo.map" --report "$W/algo.html" -v
"$W/algo" || echo "(exit status $? -- expected 20)"
echo "--- members pulled in lazily, in command-line order (hook.o is NOT pulled: a *weak* undefined reference never extracts a member, like GNU ld):"
sed -n '/Archive members pulled/,/^$/p' "$W/algo.map"
echo "--- now force it with -u optional_hook: the weak reference binds to the archive definition"
$F ld "$W/crt.o" "$W/algo.o" "$W/librt.a" -u optional_hook -o "$W/algo2"
"$W/algo2" | grep hook || true

hr "3. differential check against GNU ld: same stdout, same exit status"
$F crosscheck "$W/crt.o" "$W/algo.o" "$W/librt.a"

hr "4. --gc-sections drops unreachable code"
$F ld "$W/crt.o" "$W/algo.o" "$W/librt.a" -o "$W/algo.gc" --gc-sections -Map "$W/gc.map" -v
"$W/algo.gc" >/dev/null || true
sed -n '/Discarded input sections/,/^$/p' "$W/gc.map" | head -8

hr "5. inspectors"
$F dump "$W/librt.a"
$F nm "$W/algo" | head -6

hr "6. error handling: clear one-line diagnostics, never a traceback"
printf '.text\nmov rax, [rbx*3]\n' > "$W/bad.s"
$F as "$W/bad.s" || true
printf '.intel_syntax noprefix\n.text\n.global _start\n_start: call nowhere\n' > "$W/undef.s"
$F build "$W/undef.s" -o "$W/undef" || true

hr "7. assembler vs GNU as: 157 instruction forms, byte for byte"
python3 tests/gas_diff.py tests/corpus.s

hr "8. random differential fuzz (instruction encodings + branch relaxation)"
python3 tests/fuzz_asm.py 600 2026

echo; echo "layout report written to: tests/../ (see $W/algo.html while running; copy it out to keep it)"
