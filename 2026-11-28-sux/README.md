# Sux — succinct data structures + a compressed full-text index

A from-scratch Rust toolkit (zero dependencies) for **succinct data structures**: structures that
store data in close to the information-theoretic minimum while still answering queries in
O(1)–O(log n) *without decompressing*. They are stacked into something you can use:
`sux index` builds a self-contained index of any file; `sux grep` then answers from the index
**alone** — the original file is not needed (any byte range, or a whole line, can be regenerated from it).

## Run it
```bash
cargo build --release
./demo.sh                      # builds, runs 33 tests, then 28 end-to-end checks against grep/dd/sed/sort
cargo test --release           # just the test suite

S=target/release/sux
$S index README.md -o r.sux            # plain index
$S index big.txt -o big.sux -z --sample 64   # RRR-compressed BWT, sparser samples = smaller file
$S grep r.sux "wavelet"                # 12:A wavelet matrix ... (line numbers, from the index alone)
$S grep r.sux -- -c                    # `--`: patterns that look like flags
$S count r.sux "rank"   |  $S locate r.sux "rank" -n 5
$S extract r.sux 100 180 | $S line r.sux 3 | $S info r.sux

$S trie build words.txt -o w.trie      # LOUDS trie, one word per line
$S trie complete w.trie "ban" -n 10    # sorted completions
$S trie lookup w.trie banana           # dense id (a minimal perfect hash) ; `trie key` inverts it
$S bench                               # measured bits/item and ns/query for every structure
```
Exit codes follow grep: `grep`/`trie lookup` exit 1 when nothing matches; real errors print `sux: …` and exit 1.

## Features (all shipped)
| # | Feature | Status |
|---|---------|--------|
| 1 | **Rank/select bitvector** — rank9 directory (1.27 bits/bit total), O(1) rank, sampled select0/select1 | required ✔ |
| 2 | **Elias–Fano** — access, rank, successor, predecessor on monotone sequences, within ½ bit of the 2+log(u/n) bound | required ✔ |
| 3 | **Wavelet matrix** — access/rank/select, k-th smallest and range counting on any sub-range, next-value; 1–32 bit symbols | required ✔ |
| 4 | **FM-index** — SA-IS suffix array → BWT in a wavelet matrix → count / locate / extract / `grep` with line numbers, persisted with magic + length + FNV checksum and structural validation | required ✔ |
| 5 | **LOUDS trie** — 2 bits/node tree, lookup, dense key ids with reverse lookup, prefix completion & counting | stretch ✔ |
| 6 | **RRR compressed bitvector** — class/offset coding, used standalone and as the compressed BWT (`-z`) | stretch ✔ |
| 7 | **`sux bench`** — every number below comes from this command, nothing is hard-coded | stretch ✔ |

## Measured results (this machine; `sux bench`, full scale)
| structure | bits/item | naive | query | ns/query | naive ns |
|---|---|---|---|---|---|
| RankSelect (8 M bits) | 1.27 | 32 (prefix table) | rank1 | 17 | 14 |
| RankSelect | 1.27 | 16 | select1 | 65 | 9 (lookup table) |
| RRR (p = 0.01) | 0.37 | 1.27 (plain+dir) | rank1 | 47 | 11 |
| Elias–Fano (1 M ids, u = 2³⁰) | 12.6 | 64 | get(i) | 66 | 6 |
| Elias–Fano | 12.6 | 64 | rank(x) | 181 | 149 (binary search) |
| Wavelet matrix (1 M syms) | 10.1 | 32 | median of 1000-range | 134 | 9 559 (sort) |
| FM-index plain/32 (4 MB text) | 9.7 | 8 (raw text) | count 6-byte pattern | 3.9 µs | 6 245 µs (scan) |
| FM-index RRR/128 | 5.0 | 8 | count | 10 µs | 6 074 µs |
| LOUDS trie (100 k words) | 54 | 68 | lookup | 1.1 µs | 0.46 µs (BTreeSet) |

Honest reading: succinct structures are **smaller** (EF 5× smaller than u64s; RRR 3.4× smaller than a plain vector at p=0.01;
LOUDS smaller than raw keys) and **asymptotically better** (FM count is ~1600× faster than a scan and independent of text size),
but they are *not* faster than a flat array lookup — that's the trade. Whole-file sizes on a 1 MB English-ish corpus:
plain index/32 = 127–139 % of the text, `-z`/64 = 58–73 %, `-z`/128 ≈ 67 % (the plain index is a *replacement* for the text, not a
compression of it; `-z` is the one that genuinely shrinks it, at a large cost in `locate` speed — 80–100 µs per occurrence).
Uniformly random keys share no prefixes, so a LOUDS trie of them is no smaller than the keys; it wins on dictionary-like data.

## Architecture
```
util     error type, xorshift Rng, bounds-checked Writer/Reader, FNV-1a, seal/unseal container
bitvec   BitVec builder + RankSelect (rank9 + sampled select)
ef       Elias–Fano          rrr      RRR compressed bitvector
wavelet  wavelet matrix (plain or RRR levels)
sais     linear-time SA-IS suffix array (ported algorithm, differential-tested against sort)
fm       FM-index = wavelet BWT + sampled SA/ISA + Elias–Fano newline map
louds    LOUDS trie          bench    measured space/speed table
```
Only raw payload bits are serialised; rank/select directories are rebuilt on load, and every length,
count, alphabet and sibling-order invariant is re-validated, so a corrupt file yields an error — never a panic or a hang
(4 000-case fuzz with recomputed checksums, plain and RRR).

## Verification
`cargo test --release` — 33 tests: every structure vs a naive oracle over randomized sizes/densities (including word/superblock
boundaries), serialisation round-trips, truncation + bit-flip + checksum-repair fuzz, CLI behaviour and error paths.
`./demo.sh` — 28 checks comparing `sux grep/count/locate/extract/line/trie` to `grep -nF`, `grep -o`, `grep -ob`, `dd`, `sed`, `tail`, `sort`.
See [REVIEW.md](REVIEW.md) for the 9 review findings (two critical) and the mutation check.

## Why I built this today
The ledger is full of engines, solvers and renderers, but nothing about *space*: how to make a data structure small and still
queryable. Succinct structures are the quiet machinery behind genome aligners (BWA/Bowtie are FM-indexes), search-engine posting
lists (Elias–Fano) and compressed tries, and they compose beautifully — a bitvector becomes a wavelet matrix becomes a text index —
and every claim is checkable against a naive oracle.

## Where a human could take this next
- **Huffman-shaped wavelet tree** for true nH0 FM-index size (≈ 4.5 bits/char on English instead of ~9 plain / 5 RRR) and run-length BWT for repetitive corpora (genomes, versioned docs).
- **Rank directory tuning** (interleaved cache-line layout, `popcnt`/`pdep` select, SIMD) — select is ~7× slower than it could be.
- **Larger RRR blocks** (b = 63) to cut the 4-bit-per-15 class overhead; Elias–Fano partitioned by clusters (PEF) for inverted indexes.
- **Document listing / top-k** over the FM-index, multi-file indexes, and a persistent memory-mapped format to avoid rebuilding directories at load.
- **Bigger inputs**: SA-IS currently needs ~40× the text size in RAM; a disk-based or induced-sorting-in-place variant (or DC3 streaming) would lift that.
- A **LOUDS-based dictionary compressor** or path-decomposed trie for URL/identifier sets.
