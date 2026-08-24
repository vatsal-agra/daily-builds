# matmul.s -- 2x2 integer matrix multiply. RV32I (the base ISA this
# simulator implements) has no MUL instruction -- multiplication lives in
# the separate "M" extension -- so this ships a real `mul` subroutine
# (repeated addition) and calls it with real jal/ret function calls.
# A = [[1,2],[3,4]], B = [[5,6],[7,8]]  =>  C = [[19,22],[43,50]]
    li s0, 4096     # &A (well past this program's own code)
    li s1, 4112     # &B
    li s2, 4128     # &C

    li t0, 1
    sw t0, 0(s0)
    li t0, 2
    sw t0, 4(s0)
    li t0, 3
    sw t0, 8(s0)
    li t0, 4
    sw t0, 12(s0)

    li t0, 5
    sw t0, 0(s1)
    li t0, 6
    sw t0, 4(s1)
    li t0, 7
    sw t0, 8(s1)
    li t0, 8
    sw t0, 12(s1)

    # C[0][0] = A[0][0]*B[0][0] + A[0][1]*B[1][0]
    lw a0, 0(s0)
    lw a1, 0(s1)
    call mul
    mv s3, a0
    lw a0, 4(s0)
    lw a1, 8(s1)
    call mul
    add s3, s3, a0
    sw s3, 0(s2)

    # C[0][1] = A[0][0]*B[0][1] + A[0][1]*B[1][1]
    lw a0, 0(s0)
    lw a1, 4(s1)
    call mul
    mv s3, a0
    lw a0, 4(s0)
    lw a1, 12(s1)
    call mul
    add s3, s3, a0
    sw s3, 4(s2)

    # C[1][0] = A[1][0]*B[0][0] + A[1][1]*B[1][0]
    lw a0, 8(s0)
    lw a1, 0(s1)
    call mul
    mv s3, a0
    lw a0, 12(s0)
    lw a1, 8(s1)
    call mul
    add s3, s3, a0
    sw s3, 8(s2)

    # C[1][1] = A[1][0]*B[0][1] + A[1][1]*B[1][1]
    lw a0, 8(s0)
    lw a1, 4(s1)
    call mul
    mv s3, a0
    lw a0, 12(s0)
    lw a1, 12(s1)
    call mul
    add s3, s3, a0
    sw s3, 12(s2)

    j end

mul:                # a0 = a0 * a1  (repeated addition; a1 assumed >= 0)
    mv t3, a0
    li t4, 0
    li t5, 0
mul_loop:
    beq t5, a1, mul_done
    add t4, t4, t3
    addi t5, t5, 1
    j mul_loop
mul_done:
    mv a0, t4
    ret

end:
    ecall
