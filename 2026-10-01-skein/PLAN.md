# Skein — PLAN

## Concept
**Skein** is a toolkit of *streaming sketches*: probabilistic data structures that answer
questions about huge data streams in a few kilobytes — "how many distinct users?", "what are
the top-10 items?", "have I seen this key?", "what is the p99 latency?", "how similar are
these two documents?" — using fixed, tiny memory and a single pass.

It ships as a Go library (`sketch/`, stdlib only) plus a CLI (`skein`) that reads lines from
stdin/files, maintains every sketch at once, serialises them to a compact checksummed binary
format, and **merges** sketches built on different shards/machines — the property that makes
sketches useful in real distributed analytics.

## Why interesting
Nothing like it in the repo ledger (no probabilistic data structures yet). Each structure
trades exactness for orders-of-magnitude less memory with *provable* error bounds, and the
fun is that we can verify those bounds empirically against exact ground truth.

## Architecture
```
sketch/hash.go      xxHash64 from scratch (+ seeded derivations, double hashing)
sketch/hll.go       HyperLogLog (64-bit hash, LogLog-Beta-free: linear counting + Ertl improved estimator)
sketch/cms.go       Count-Min sketch (conservative update) + SpaceSaving heavy hitters
sketch/bloom.go     Bloom filter (optimal sizing, union) ; cuckoo.go  Cuckoo filter (delete)
sketch/tdigest.go   Merging t-digest (k1 scale function) quantiles/CDF
sketch/minhash.go   MinHash signatures + banded LSH index           (stretch)
sketch/codec.go     versioned binary format, CRC32, Marshal/Unmarshal for every type
sketch/report.go    accuracy-vs-memory benchmark -> self-contained HTML/SVG report  (stretch)
cmd/skein           CLI: stats | count | top | member | quantile | sim | merge | inspect | report
```

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | HyperLogLog cardinality (precision 4–18, Ertl estimator, merge) | **required** |
| 2 | Count-Min sketch + SpaceSaving top-K heavy hitters (merge) | **required** |
| 3 | Bloom filter + Cuckoo filter (membership; cuckoo supports delete) | **required** |
| 4 | t-digest quantiles/CDF with merge, plus CLI single-pass `stats` over streams with binary save/load/merge | **required** |
| 5 | MinHash + banded LSH similarity (Jaccard estimate, near-duplicate lookup) | stretch |
| 6 | Self-contained HTML accuracy-vs-memory report (empirical error vs theoretical bound) | stretch |
| 7 | Sliding-window/decay variants | stretch (only if time) |

## Definition of done
Every sketch's measured error is within its theoretical bound in tests; serialisation
round-trips and rejects corruption; merge(a,b) == sketch of concatenated stream (exact for
HLL/Bloom/CMS; within tolerance for t-digest).
