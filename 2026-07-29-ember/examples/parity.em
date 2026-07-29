// Mutual recursion: is_even calls is_odd, which is defined *after* it in
// the source. Forces the codegen's forward-call label-fixup machinery --
// is_even's `call` instruction targets an address that doesn't exist yet
// at the point the call is emitted.
fn is_even(n) {
    if (n == 0) {
        return 1;
    }
    return is_odd(n - 1);
}

fn is_odd(n) {
    if (n == 0) {
        return 0;
    }
    return is_even(n - 1);
}
