# Plinth

Journaling filesystem + crash-consistency lab (Rust, zero deps). See [PLAN.md](PLAN.md).

**Status: Phase 2 (core build) done.** The four required features work end to end:

| # | Feature | Where |
|---|---------|-------|
| R1 | ext2-style filesystem (inodes, bitmaps, direct/indirect/double-indirect, dirs, symlinks, hard links, rename, truncate, sparse files) | `src/fs.rs`, `src/layout.rs` |
| R2 | Write-ahead journal, CRC-protected, 3-barrier commit, idempotent replay | `src/journal.rs` |
| R3 | fsck analysis (bitmaps, link counts, double-claimed blocks, orphans, `.`/`..`, counters) | `src/fsck.rs` |
| R4 | Differential fuzzer vs. reference model + crash-state fuzzer (record/replay, subsets, torn writes) | `src/model.rs`, `src/fuzz.rs` |

Try: `cargo test --release`.
