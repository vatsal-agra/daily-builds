# Minimal C runtime: _start -> main(), plus raw syscall wrappers.
.intel_syntax noprefix
.text
.global _start, sys_write, sys_exit
_start:
    xor ebp, ebp
    and rsp, -16
    call main
    mov edi, eax
    call sys_exit
sys_write:                 # long sys_write(int fd, const void *buf, unsigned long n)
    mov eax, 1
    syscall
    ret
sys_exit:                  # void sys_exit(int code)
    mov eax, 60
    syscall
    ud2
.section .note.GNU-stack,"",@progbits
