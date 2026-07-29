// Short-circuit && / || proven by construction, not just by truth
// table: guard(a, b) divides b by a inside the right-hand operand of
// `&&`. If `&&` were eagerly evaluating both sides (a common bug when a
// codegen author reaches for bitwise AND/OR instead of real branching),
// guard(0, 5) would divide by zero. It doesn't, because a == 0 makes the
// left side false and the right side is never evaluated.
fn guard(a, b) {
    return a != 0 && b / a > 1;
}

fn either(a, b) {
    return a == 0 || b / a > 1;
}

fn logical_not(a) {
    return !a;
}
