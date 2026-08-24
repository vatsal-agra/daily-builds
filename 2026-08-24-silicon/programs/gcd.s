# gcd.s -- Euclid's algorithm by repeated subtraction (RV32I has no DIV/REM
# instruction -- those live in the M extension -- so subtraction is the
# genuine base-ISA way to do this). Computes gcd(1071, 462) = 21 and
# stores it to mem[0].
    li a0, 1071
    li a1, 462
loop:
    beq a0, a1, done
    blt a0, a1, a_smaller
    sub a0, a0, a1
    j loop
a_smaller:
    sub a1, a1, a0
    j loop
done:
    sw a0, 0(x0)
    ecall
