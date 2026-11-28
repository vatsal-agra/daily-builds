# Sux — a succinct data structures toolkit (Rust, zero dependencies)

## Concept
Succinct data structures store data in (nearly) the information-theoretic minimum
of space while still answering queries in O(1)–O(log n) *without decompressing*.
Sux builds the classic stack from the ground up and wires it into something you can
actually use: a **compressed full-text index** you can `grep`, that stores *no copy of the text* and
can regenerate any part of it from itself alone (and, with RRR levels, shrinks below the file size).

## Why it's interesting
- It is the machinery behind genome aligners (BWA, Bowtie), Lucene's posting lists
  (Elias–Fano), and modern compressed tries. Nothing in this repo touches it yet.
- Every layer is built on the one below: bitvector → Elias–Fano / wavelet matrix → FM-index.
- Correctness is checkable: every structure has a naive oracle and randomized
  differential tests; space is *measured*, not claimed.

## Architecture
```
util      xorshift Rng, little-endian Writer/Reader with bounds-checked errors, FNV-1a checksum
bitvec    BitVec (builder) + RankSelect (rank9 directory, sampled select0/select1)
ef        Elias–Fano monotone sequences (access, rank, successor, predecessor)
wavelet   Wavelet matrix (access, rank, select, k-th smallest, range count, range-next)
sais      SA-IS linear-time suffix array
fm        FM-index = BWT in a wavelet matrix + sampled SA/ISA + Elias–Fano line map
rrr       RRR entropy-compressed bitvector (class/offset, combinatorial number system)
louds     LOUDS succinct trie (lookup, rank-of-key, key-of-rank, prefix enumeration)
main      CLI: index / grep / count / extract / info / trie / bench / selftest
```
Binary container: magic + version + payload + FNV checksum; loading corrupt data
returns an error, never panics.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | Rank/select bitvector (rank9, 25% overhead, O(1) rank, fast select0/select1) | **required** |
| 2 | Elias–Fano sequence: access, rank, successor/predecessor, ~2+log(u/n) bits/elem | **required** |
| 3 | Wavelet matrix: access/rank/select, k-th smallest, range counting over any range | **required** |
| 4 | FM-index over SA-IS: count / locate / extract + `grep` with line numbers from the index alone, persisted to disk with checksum | **required** |
| 5 | LOUDS succinct trie: exact lookup, key↔id mapping, prefix completion | stretch |
| 6 | RRR compressed bitvector (sub-n bits on skewed data, rank/access) | stretch |
| 7 | `bench`: measured bits/element and ns/query vs naive for every structure | stretch |

## Done means
Every feature has a randomized differential test against a naive oracle, a CLI
path that exercises it end to end, `demo.sh` runs green, REVIEW.md lists real findings and fixes.
