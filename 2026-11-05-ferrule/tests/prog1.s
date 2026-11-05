.intel_syntax noprefix
.section .rodata
msg:    .asciz "hi\n\t\"q\"\x41\101"
nums:   .byte 1, 2, 0xff, -1
        .word 0x1234, -2
        .long 0xdeadbeef, ext_sym, msg - nums
        .quad 0x1122334455667788, nums, ext_sym + 8
.align 8
tbl:    .quad f1, f2, f3
        .zero 5
        .ascii "ab"
.data
.global gvar
gvar:   .long 42
        .quad gvar
.comm common_buf, 64, 16
.bss
.global zbuf
zbuf:   .zero 100
.text
.global _start
.type _start, @function
_start:
    lea rdi, [rip + msg]
    mov eax, offset offset_c
    mov rsi, offset OFFS
    call f1
    call ext_func
    jmp far_label
f1:
    cmp eax, 3
    jl .Lshort
    jmp .Lshort
    .rept_pad_none:
.Lshort:
    jne f1
    je f2
    jmp f3
f2: nop
    .skip 130, 0x90
f3: jne f2
    jmp f2
    mov rax, [rip + gvar]
    mov rax, [rip + ext_sym + 4]
    mov rax, [gvar]
    mov rax, [gvar + rcx*8]
    mov dword ptr [rip + gvar], 7
    mov dword ptr [rip + gvar], 0x7777
    add dword ptr [rip + gvar], 5
    mov rax, offset gvar
    mov eax, offset gvar
    lea rax, [rip + zbuf + 4]
    call [rip + ext_ptr]
.align 16
far_label:
    ret
.p2align 4
    nop
.balign 8, 0xcc
    mov eax, f3 - f1
    .set OFFS, 0x10
    .equ offset_c, 12
.size _start, . - _start
.weak weakfn
.section .note.GNU-stack,"",@progbits
