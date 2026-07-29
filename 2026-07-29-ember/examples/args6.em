// System V AMD64 passes the first 6 integer arguments in
// rdi/rsi/rdx/rcx/r8/r9 -- the last two require an extra REX.R/REX.B bit
// the low eight registers don't need. This function is Ember's maximum
// arity (MAX_PARAMS = 6) specifically to force the encoder to exercise
// r8 and r9, not just the "easy" low registers.
fn weighted_sum(a, b, c, d, e, f) {
    return a * 1 + b * 2 + c * 3 + d * 4 + e * 5 + f * 6;
}
