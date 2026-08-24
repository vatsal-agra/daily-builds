# bubblesort.s -- in-place bubble sort of a 6-element array built in
# memory at address 4096 (well past this program's own code, so the array
# writes can't clobber not-yet-executed instructions). A nested-loop
# program with a data-dependent inner branch (whether to swap) on top of
# the loop back-edges -- good mixed hazard/branch-prediction stress.
# Leaves the sorted array (1 2 3 5 8 9) in memory at 4096..4116; nothing
# else needs verifying since both simulators' full memory image is checked.
    li t0, 4096     # array base (well past this program's own code)
    li t1, 5
    sw t1, 0(t0)
    li t1, 3
    sw t1, 4(t0)
    li t1, 8
    sw t1, 8(t0)
    li t1, 1
    sw t1, 12(t0)
    li t1, 9
    sw t1, 16(t0)
    li t1, 2
    sw t1, 20(t0)

    li s0, 6        # n
    li s1, 0        # i
outer:
    bge s1, s0, outer_done
    li s3, 0        # j
    addi s4, s0, -1
    sub s4, s4, s1  # inner bound = n - 1 - i
inner:
    bge s3, s4, inner_done
    slli t2, s3, 2
    add t3, t0, t2
    lw t4, 0(t3)    # arr[j]
    lw t5, 4(t3)    # arr[j+1]
    blt t5, t4, doswap
    j noswap
doswap:
    sw t5, 0(t3)
    sw t4, 4(t3)
noswap:
    addi s3, s3, 1
    j inner
inner_done:
    addi s1, s1, 1
    j outer
outer_done:
    ecall
