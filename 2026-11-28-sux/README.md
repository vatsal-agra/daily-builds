# Sux
Status: **Phase 3 (adversarial review) complete** — 9 findings fixed, see [REVIEW.md](REVIEW.md). Succinct data structures + compressed full-text index in Rust, zero dependencies. See [PLAN.md](PLAN.md).

Built and tested so far (all differential-tested against naive oracles — `cargo test --release`):
- **Rank/select bitvector** (rank9 directory, sampled select0/select1)
- **Elias–Fano** monotone sequences (access, rank, successor, predecessor)
- **Wavelet matrix** (access, rank, select, k-th smallest, range counting, next-value)
- **FM-index** over an SA-IS suffix array: count / locate / extract / grep-with-line-numbers, persisted with a checksum (`sux index|grep|count|locate|extract|line|info`)
- **RRR** compressed bitvector (also used as an optional compressed BWT via `sux index -z`)
