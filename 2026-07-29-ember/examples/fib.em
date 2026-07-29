// Naive recursive Fibonacci -- exponential call count, the classic
// "make the interpreter sweat, then compare it to native code" benchmark.
fn fib(n) {
    if (n < 2) {
        return n;
    }
    return fib(n - 1) + fib(n - 2);
}
