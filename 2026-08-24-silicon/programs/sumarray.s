# sumarray.s -- builds a 10-element integer array in memory (via stores;
# this ISA has no data-section directive, so the array is constructed by
# code, which is honest and self-contained), then sums it. Every loop
# iteration issues a load immediately followed by an instruction that
# consumes it (lw -> add) -- a textbook load-use hazard, exercised 10
# times. Stores the sum (39) to mem[8192].
    li t0, 4096     # array base address (well past this program's own code)
    li t1, 3
    sw t1, 0(t0)
    li t1, 1
    sw t1, 4(t0)
    li t1, 4
    sw t1, 8(t0)
    li t1, 1
    sw t1, 12(t0)
    li t1, 5
    sw t1, 16(t0)
    li t1, 9
    sw t1, 20(t0)
    li t1, 2
    sw t1, 24(t0)
    li t1, 6
    sw t1, 28(t0)
    li t1, 5
    sw t1, 32(t0)
    li t1, 3
    sw t1, 36(t0)

    li t2, 0        # sum
    li t3, 10       # count
    li t4, 0        # index
sumloop:
    beq t4, t3, sumdone
    slli t5, t4, 2
    add t6, t0, t5
    lw a0, 0(t6)    # load-use hazard: a0 is consumed by the very next instr
    add t2, t2, a0
    addi t4, t4, 1
    j sumloop
sumdone:
    li t5, 8192     # result address (12-bit store-offset immediates can't
    sw t2, 0(t5)    # reach 8192 directly, so materialize it in a register)
    ecall
