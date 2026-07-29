// Euclidean GCD -- exercises `%`, `while`, multi-variable swaps via a
// temporary local.
fn gcd(a, b) {
    while (b != 0) {
        let t = b;
        b = a % b;
        a = t;
    }
    return a;
}
