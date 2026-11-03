# Cairn — garbage-collector laboratory

Status: **Phase 3 (adversarial review) complete** — see [REVIEW.md](REVIEW.md) (13 findings, all fixed; `./review_check.sh` re-probes them). Phases 4–6 add the bench harness, HTML report, polish and the full README.
generational with remembered set, incremental SATB, sliding mark-compact) behind one `Gc` trait, a
Lisp-flavoured mutator language + GC-safe VM, and an oracle (canonical graph snapshots + heap
checks). See [PLAN.md](PLAN.md). Quick try:

    cargo build --release
    ./target/release/cairn run examples/cycles.cairn --gc incremental --stats
    cargo test --release

Full README arrives in the ship phase.
