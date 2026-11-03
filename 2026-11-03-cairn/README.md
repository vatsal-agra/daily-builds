# Cairn — garbage-collector laboratory

Status: **Phase 4 (stretch + polish) complete** — added mark-compact, bench harness with MMU, HTML report, differential fuzzer, `barrier-demo`. Phases 5–6 add the verification gate and the full README.
generational with remembered set, incremental SATB, sliding mark-compact) behind one `Gc` trait, a
Lisp-flavoured mutator language + GC-safe VM, and an oracle (canonical graph snapshots + heap
checks). See [PLAN.md](PLAN.md). Quick try:

    cargo build --release
    ./target/release/cairn run examples/cycles.cairn --gc incremental --stats
    cargo test --release

Full README arrives in the ship phase.
