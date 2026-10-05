# Skein

**Streaming probabilistic data structures in Go (stdlib only) — plus a CLI that uses them.**
Answer "how many distinct?", "what's most frequent?", "have I seen it?", "what's the p99?" and
"how similar are these?" over data too big to hold, in kilobytes and a single pass — with error
bounds that the test-suite checks against exact ground truth. Sketches serialise to a
checksummed binary format and **merge**, so shards computed on different machines combine
without re-reading any data.

```
go build -o skein ./cmd/skein
./skein stats -f 1 -v 2 access.tsv          # one pass: distinct, top-K, quantiles
./skein report -o report.html               # measured-vs-theory accuracy charts
go test ./...                               # 39 tests (sketch bounds, fuzzing, CLI e2e)
./demo.sh                                   # guided tour of every feature
```
Requires Go ≥ 1.21. No third-party dependencies.

## Features

| Sketch | What it answers | Memory | Highlights |
|---|---|---|---|
| **HyperLogLog** | distinct count | 2^p bytes (16 KiB → ±0.81%) | Ertl's improved estimator (no bias tables, accurate from n=0 to billions), merge, intersection estimate |
| **Count-Min** | frequency of any key | w×d×4 B | conservative update, ε/δ sizing, never under-counts, merge |
| **SpaceSaving** | top-K heavy hitters | k entries | every item with freq > N/k guaranteed present, per-item `[count−err, count]` bounds, mergeable-summaries merge, heap-backed O(log k) |
| **Bloom filter** | set membership | ~10 bits/key @1% | optimal sizing, double hashing, union, cardinality estimate from fill ratio |
| **Cuckoo filter** | membership **with delete** | 16-bit fingerprints | partial-key cuckoo hashing, atomic failed-insert rollback, `AddUnique` set semantics |
| **t-digest** | quantiles / CDF | ~1 KiB | merging digest with k₁ scale (tail-accurate), merge across digests |
| **MinHash + LSH** | Jaccard similarity, near-dup search | k×8 B | auto-tuned banding for a target threshold |
| **Codec** | save / load / merge | — | versioned frame, CRC-32, strict structural validation (fuzzed) |
| **xxHash64** | the hash under everything | — | written from the spec, checked against official vectors |

### CLI

| Command | Purpose |
|---|---|
| `skein stats [-f key] [-v value] [-o state] [-load state]` | one pass over a log: distinct keys, top-K with bounds, frequencies, value quantiles; incremental updates via `-load` |
| `skein count` / `top` / `quantile` | single-purpose versions; `-exact` shows the true answer and your error |
| `skein member build\|check\|del` | Bloom (default) or `-cuckoo` filters; `check` exits 3 if any key is absent (grep-style) |
| `skein sim A B` / `skein dups` | MinHash Jaccard of two files / LSH near-duplicate lines |
| `skein merge -o out a.skn b.skn …` | combine shard states (type- and parameter-checked; refuses mismatches) |
| `skein inspect file.skn` | describe + verify a saved sketch |
| `skein report -o report.html` | benchmark all six structures against ground truth → self-contained, dark-mode-aware HTML with inline SVG charts |

Input: lines from files or stdin; `-d` delimiter (default tab) and 1-based `-f`/`-v` field
numbers. Unparsable lines are skipped and counted on stderr.

### Sample output (400k-line Zipf log, 27 469 true distinct keys)
```
$ skein count -f 1 -exact all.tsv
lines 400000, distinct ≈ 27641 (±0.81%, 16.0 KiB)
exact distinct = 27469, error +0.625%

$ skein quantile -v 2 -q 0.5,0.99 -exact all.tsv
n=400000  min=0.54  max=1249.134  (59 centroids, 944 B)
  p50      20.1197      exact 20.109
  p99      129.984      exact 128.538
```

## Design notes
* **Why merge matters:** HLL (register-wise max), Bloom (bitwise OR) and MinHash (min) merge
  *exactly* — merged == single-pass, which the CLI tests assert. t-digest and SpaceSaving merge
  with preserved guarantees; Count-Min merges by summing (still never under-counts, slightly looser).
* **Honest bounds:** SpaceSaving reports `[count−err, count]` intervals; Count-Min reports ε·N.
  Tests verify the true value lands inside.
* **Cuckoo gotcha handled:** a cuckoo filter can hold ≤8 copies of one fingerprint, so streams
  with repeated keys need set semantics (`AddUnique`) — found by running it on a real log.
* **Not goroutine-safe** by design: shard the stream and merge.
* **Limits:** no CSV quote parsing; cuckoo filters can't merge; HLL intersection is noisy for small overlaps.

## Process artefacts
`PLAN.md` (concept + feature table), `REVIEW.md` (adversarial review: 10 issues found and fixed),
`demo.sh`, `sketch/*_test.go`, `cmd/skein/cli_test.go`. Tests were also mutation-checked: I broke
10 pieces of logic on purpose and confirmed the suite caught each (one equivalent mutant exposed a
missing weighted-add test, which I then added).

## Why I chose this today
The ledger is heavy on engines, VMs, compilers and renderers but had **zero** probabilistic data
structures — a whole family where the interesting part isn't "does it run" but "is the error
really within the proven bound?". That makes the result verifiable rather than merely plausible,
and the merge property gives it a genuine systems story (sharded analytics) instead of a pile of
algorithms.

## Where a human could take this next
* **Sliding-window / decaying sketches** (exponential-decay Count-Min, windowed HLL) — the unbuilt stretch item.
* **HLL++ sparse representation** so tiny cardinalities cost bytes, not 16 KiB; Θ-sketches for set algebra.
* **A network daemon** (`skein serve`): POST lines, GET `/distinct`, with periodic snapshotting to the codec format — plus Prometheus export.
* **Parallel ingest:** per-core sketches merged at the end (already safe by construction).
* **Cuckoo → Xor/Ribbon filters** for static sets at ~9 bits/key; counting Bloom variants.
* **Compatibility:** read/write Redis/Datasketches HLL formats so Skein can interoperate.
* **CSV/JSON field extraction** (`-f` by name) for real log formats.
