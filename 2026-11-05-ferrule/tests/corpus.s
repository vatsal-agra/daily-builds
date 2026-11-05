.intel_syntax noprefix
.text
start:
    mov rax, rbx
    mov eax, ebx
    mov ax, bx
    mov al, bl
    mov sil, dil
    mov r8, r15
    mov r9d, r10d
    mov r11w, r12w
    mov r13b, r14b
    mov rax, 1
    mov rax, -1
    mov eax, 0x12345678
    mov rax, 0x123456789a
    mov r10, 0x7fffffff
    mov al, 7
    mov ax, 300
    mov r12d, 5
    mov rax, [rbx]
    mov rax, [rbx+8]
    mov rax, [rbx-8]
    mov rax, [rbx+0x1000]
    mov rax, [rsp]
    mov rax, [rsp+16]
    mov rax, [rbp]
    mov rax, [r12]
    mov rax, [r13]
    mov rax, [r13+4]
    mov rax, [rax+rcx*8]
    mov rax, [rax+rcx*8+0x40]
    mov rax, [rcx*4+0x100]
    mov [rbx+rsi*2], edx
    mov qword ptr [rbx], 5
    mov dword ptr [rbx+4], 0x11223344
    mov word ptr [rbx], 7
    mov byte ptr [rbx], 9
    mov byte ptr [r9+rax], 200
    lea rax, [rbx+rcx*4+3]
    lea r10, [rip+0x20]
    lea edx, [rax+rax*2]
    add rax, rbx
    add rax, 5
    add rax, 0x1000
    add eax, 0x1000
    add al, 3
    add rbx, 0x1000
    add dword ptr [rbp-4], 1
    add qword ptr [rsp+8], -8
    sub rsp, 0x28
    sub rsp, 8
    and rsp, -16
    or eax, 0x80
    xor eax, eax
    xor r8d, r8d
    cmp rax, 0
    cmp rax, 100000
    cmp byte ptr [rdi], 0
    cmp al, 10
    cmp rcx, [rdx+8]
    adc rax, rdx
    sbb eax, 1
    test rax, rax
    test eax, 0x100
    test al, 1
    test byte ptr [rdi], 4
    test r8b, r9b
    inc rax
    dec ecx
    inc qword ptr [rbx]
    neg rax
    not edx
    mul rcx
    imul rbx
    idiv rcx
    div dword ptr [rbp-8]
    imul rax, rbx
    imul rax, [rbx+4]
    imul rax, rbx, 10
    imul rax, rbx, 1000
    imul eax, 7
    shl rax, 1
    shl rax, 4
    shr edx, cl
    sar r8, 63
    rol eax, 3
    ror rax, 1
    movzx eax, al
    movzx eax, byte ptr [rdi]
    movzx r8d, word ptr [rsi]
    movsx rax, bl
    movsx eax, word ptr [rdi]
    movsxd rax, ecx
    movsxd rdx, dword ptr [rsi+rdi*4]
    cdq
    cqo
    cdqe
    push rax
    push r12
    pop rbx
    pop r15
    push 5
    push 0x1000
    push qword ptr [rbx]
    pop qword ptr [rbx+8]
    xchg rax, rbx
    xchg rcx, rdx
    xchg [rdi], eax
    cmove rax, rbx
    cmovne eax, [rdi]
    cmovg r8, r9
    sete al
    setne byte ptr [rdi]
    setl r8b
    seta sil
    bswap eax
    bswap r9
    bt rax, 5
    bt eax, ecx
    bts qword ptr [rdi], 3
    bsf rax, rbx
    bsr eax, [rdi]
    popcnt rax, rbx
    lock cmpxchg [rdi], ecx
    lock xadd [rdi], rax
    lock add dword ptr [rdi], 1
    rep movsb
    rep stosq
    rep movsq
    repne scasb
    call rax
    call [rbx+8]
    jmp rcx
    jmp qword ptr [rax*8+0x100]
    syscall
    ret
    leave
    nop
    int3
    hlt
    ud2
    cpuid
    pause
    rdtsc
    mfence
    movabs rax, 0x1122334455667788
    mov rax, 0x80000000
    mov rax, -0x80000000
    mov eax, -1
    mov [rax], rsp
    mov [r13+r14*8], r15
    mov r15, [r12+r13*8+0x7f]
    mov r15, [r12+r13*8+0x80]
    mov cl, ah
    mov ah, 5
    mov bh, [rax]
