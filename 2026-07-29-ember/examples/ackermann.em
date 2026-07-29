// The Ackermann function -- not primitive recursive, grows absurdly
// fast, and its call tree is deep and irregular rather than the neat
// binary tree Fibonacci has. Good stress test for the call/return path
// and stack-alignment bookkeeping across many nested `call`s.
fn ackermann(m, n) {
    if (m == 0) {
        return n + 1;
    }
    if (n == 0) {
        return ackermann(m - 1, 1);
    }
    return ackermann(m - 1, ackermann(m, n - 1));
}
