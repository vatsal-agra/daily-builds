# Kripke — symbolic model checker (in progress)

Status after **phase 2 (core build)**:

* `src/bdd.rs` — BDD engine (hash-consing, ITE, ∃/∀, relational product, rename, satcount, GC, in-place level swap, block sifting)
* `src/lang.rs`, `src/model.rs` — SMV-style language → symbolic transition system
* `src/check.rs` — reachability, deadlocks, `INVARSPEC` with shortest counterexample, fair CTL (Emerson–Lei) with witnesses/lassos
* `src/ltl.rs` — LTL via tableau product (stretch, already working)
* `src/explicit.rs`, `src/fuzz.rs` — independent explicit-state oracle + random differential testing (stretch, already working)

Try it: `cargo run --release -- examples/peterson.smv`

See [PLAN.md](PLAN.md). The README is rewritten in full at phase 6.
