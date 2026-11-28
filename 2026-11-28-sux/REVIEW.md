# REVIEW — adversarial pass on Sux

I attacked the code as a hostile reviewer: size extremes, corrupt-but-checksummed
files, argument parsing, scale, and "does the number in my own plan actually hold?".
Each finding below was **reproduced first** (a failing test or a command), then fixed.
Regression tests live in `tests/hostile.rs` and `tests/cli.rs`.

| # | Severity | Finding (reproduction) | Fix |
|---|----------|------------------------|-----|
| 1 | **Critical** | `EliasFano::with_universe(&[], 1<<40)` computed `l = 0` for an empty sequence, so the unary half allocated `universe` bits → **137 GB allocation, process abort**. The same flaw silently wasted 1 bit/char for every text with no newlines (FM-index newline map has universe = n+1 and n = 0 entries). | Empty sequence is sized as one element, so the unary part is O(n+1) bits regardless of universe. Test `ef_empty_or_sparse_does_not_allocate_per_universe`. |
| 2 | **Critical** | A *checksum-valid* but structurally corrupt index (bit-flip + recomputed FNV; my fuzz hit it at round 167) made `locate` loop forever: the LF-walk looks for a sampled row, and a corrupt marker bitvector has none on the cycle. Same fuzz class could also reach a `k == 0` sentinel in `extract` (an indexing underflow in release builds). | `locate_row` is bounded by `sample_rate` LF steps (the provable maximum for a valid index) and returns `Error::Corrupt`; `extract` returns `Corrupt` on the sentinel; located positions are range-checked. 4,000 random corruptions × plain/RRR now neither panic nor hang (10 s watchdog per case). |
| 3 | High | `sux grep idx -c` silently swallowed `-c` as a flag, so a pattern that looks like an option was unsearchable; unknown `--options` were treated as the pattern. | Flags are parsed globally; unknown options are an error; `--` makes everything after it positional. |
| 4 | High | `sux index` wrote the output in place: a crash/full disk mid-write left a truncated index that *looks* like the real one (it would fail the length/checksum test, but it also destroyed the previous good index). | Write to `<out>.tmp`, then atomic rename. |
| 5 | Medium | My own PLAN claimed the FM-index is "smaller than the file". Measured on a 1.2 MiB English corpus: plain index = **139%** of the text (a plain wavelet matrix costs ⌈log σ⌉ bits/char, samples cost 2 bits/char more). The claim was false as stated. | Kept the honest behaviour and made the trade-off a feature: `-z` stores the BWT as RRR levels and `--sample N` sets sampling density. Measured: plain/32 = 139%, `-z`/32 = 86%, `-z`/128 = 67%. README states the real numbers and the query-time cost. PLAN.md wording corrected. |
| 6 | Medium | Misleading error: `extract 5 3` said "range 5..3 outside text of length 1251807". | Distinct messages for start>end and end>len. |
| 7 | Medium | `count(b"")` returned n+1 with no documentation; CLI would have printed it as a match count. | Documented (n+1 positions incl. end), CLI rejects empty patterns, test pins the behaviour. |
| 8 | Low | RRR first cut used 32-block superblocks: 44% of raw bits on a p=0.01 vector (4-bit classes alone are 26.7%). | 64-block superblocks → test demands < 42%; documented that b=15 RRR only wins on sparse/dense vectors. |
| 9 | Low | Wavelet matrix with 32-bit symbols and query symbols wider than the matrix were untested (shift-overflow risk). | Test `wavelet_handles_full_32_bit_symbols` (passes; no code change needed). |

## Checked and found sound
- rank/select vs naive for n ∈ {0,1,63,64,65,511,512,513,…,70 000} × density {0, .01, .5, .99, 1}, including `rank(len)` and `select` one-past-the-end.
- EF duplicates, `u64::MAX - 1`, predecessor/successor at both ends.
- SA-IS against `sort` on 1-, 2-, 3-symbol alphabets, all-equal text, and periodic text.
- Texts containing NUL and all 256 byte values (sentinel mapping is by compaction, not by reserving a byte).
- Trailing-newline / no-trailing-newline / empty-file line counts.
- Scale: 20 MB corpus indexes in 6.5 s, `count` in 90 ms, `grep` in 110 ms (RRR index: 120 ms).

## Not fixed (documented limits)
- SA-IS uses `usize` arrays: indexing needs roughly 40× the text size in RAM at peak. Text limited to < 4 GiB by u32 samples.
- RRR rank scans up to 64 class nibbles; it is a space-first structure.

## Gate: fresh run-through
`cargo test --release` (all suites) green, and every reproduction above re-run against the fixed build produces the fixed behaviour.

## Phase 5 verification notes
- `cargo test --release`: 33 tests across 7 suites, plus `./demo.sh` (28 end-to-end checks against `grep -nF`, `grep -ob`, `dd`, `sed`, `tail`, `sort`).
- Mutation check (6 injected bugs): EF bucket compare, wavelet child-range, RRR decode boundary → caught by failures; LOUDS parent formula → caught (the suite hangs on the broken `key_of`); two survivors are *equivalent* mutants (the select0 padding mask is unreachable behind the `k < count_zeros` guard; sampling `extract` from a later row is merely slower, still correct).
