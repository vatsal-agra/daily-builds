# fibonacci.s -- iterative Fibonacci. Computes fib(15) and stores it to
# mem[0]. A tight loop with a back-edge branch taken 14 times then not
# taken once -- exactly the shape that makes dynamic branch prediction
# shine over static predict-not-taken.
    li t0, 0        # a = fib(0)
    li t1, 1        # b = fib(1)
    li t2, 15       # n
    li t3, 0        # i
loop:
    beq t3, t2, done
    add t4, t0, t1  # t4 = a + b
    mv t0, t1
    mv t1, t4
    addi t3, t3, 1
    j loop
done:
    sw t0, 0(x0)
    ecall
