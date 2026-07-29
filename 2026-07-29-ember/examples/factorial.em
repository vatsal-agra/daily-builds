// Iterative factorial -- exercises `let`, `while`, and reassignment.
fn factorial(n) {
    let acc = 1;
    while (n > 1) {
        acc = acc * n;
        n = n - 1;
    }
    return acc;
}

// Recursive factorial too, so the two can be cross-checked against
// each other as well as against the interpreter/gcc oracles.
fn factorial_rec(n) {
    if (n <= 1) {
        return 1;
    }
    return n * factorial_rec(n - 1);
}
