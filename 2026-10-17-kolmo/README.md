# Kolmo

A from-scratch **lossless compression laboratory** in Go — standard library only (and even `compress/*` is used
solely as an independent test oracle). Three generations of compressor design behind one self-describing,
checksummed container, so you can watch "better prediction = smaller file" climb from 1977 to the PAQ lineage on
your own data.

| generation | method | what's inside |
|---|---|---|
| LZ77 + Huffman | `deflate` | RFC 1951 compressor **and** decompressor, gzip (RFC 1952) wrapper; readable by `gzip(1)` and vice-versa |
| block sorting | `bwt` | suffix-array Burrows–Wheeler → MTF → RUNA/RUNB zero-runs → multi-table canonical Huffman |
| context mixing | `cm` | 8 hashed contexts + match model → 3 gated logistic mixers → 2 APM stages → 32-bit binary arithmetic coder |
| entropy coding | `rans0`, `rans1` | static order-0 / order-1 range ANS |

## Run it

```bash
cd 2026-10-17-kolmo
go build -o kolmo ./cmd/kolmo

./kolmo compress notes.txt                 # auto: tries every method in parallel, keeps the smallest -> notes.txt.kol
./kolmo compress -m cm notes.txt -o n.kol  # force a method (auto | store | deflate | bwt | cm | rans0 | rans1)
./kolmo decompress notes.txt.kol           # CRC-32 verified; also reads plain .gz files
./kolmo inspect notes.txt.kol              # container header
./kolmo bench a.txt b.bin                  # every method side by side, round-trip verified
./kolmo heat -o report.html notes.txt      # per-byte cost map (open in a browser)
./kolmo gzip -l 9 f > f.gz                 # real gzip output from our encoder
./kolmo gunzip f.gz                        # decoded by our inflate

./demo.sh        # builds, runs every feature end to end, then the whole test-suite
go test ./...    # unit, fuzz-style, interop (stdlib + system gzip), and CLI tests
```

## Results

254 KB of English/markdown prose (`LEDGER.md`), bytes:

| gzip -9 | **Kolmo deflate 9** | xz -9e | bzip2 -9 | **Kolmo bwt** | **Kolmo cm** |
|---:|---:|---:|---:|---:|---:|
| 91 987 | 92 047 | 81 656 | 77 083 | 77 924 | **67 937** (−26% vs bzip2) |

The cm model costs ~3 s/MB each way (symmetric, like all CM compressors); bwt ≈ 0.25 s/MB; deflate ≈ 0.07 s/MB.
On incompressible data `auto` correctly falls back to `store` (+13 bytes of header). On a 4-letter DNA alphabet,
rans0 lands within 0.1% of the 2-bit entropy bound.

## Features (all shipped)

1. **DEFLATE / gzip** — hash-chain LZ77 with lazy matching, 9 levels (zlib's tuning table), stored/fixed/dynamic block selection by exact bit cost, length-limited package-merge Huffman, own inflate with bounded output, multi-member gzip. Verified against `compress/flate` at every level in both directions and against the system `gzip`.
2. **BWT block-sorting** — prefix-doubling suffix sort (radix, O(n log n)), MTF, bijective-base-2 zero-run coding, up to six Huffman tables chosen per 50-symbol group by iterative refinement; 1 MiB blocks.
3. **Context mixing** — orders 0–4 and 6, word and sparse contexts, adaptive-rate counters, match model, three weight-set-selected mixers averaged in the logistic domain, two interpolating APMs; integer-only arithmetic after table init, with the `exp` table built from correctly rounded IEEE operations so the format is platform independent.
4. **KOL1 container + CLI** — method registry, CRC-32, best-of auto selection (parallel), strict decoders (truncation / trailing bytes / bit flips all rejected), size-bomb guard (expansion bounded per method *before* allocating), overwrite protection, stdin/stdout.
5. *(stretch)* **rANS** order-0 and order-1 with 12-bit models.
6. *(stretch)* **`heat`** — dark-mode-aware HTML report: bits/byte, cost histogram, most surprising lines, annotated text where every byte is shaded by what the CM model paid for it.
7. *(stretch)* **DEFLATE levels 1–9**.
8. *(stretch)* **BWT multi-table Huffman** (closed review finding R11: ‑3.5% size).

See [PLAN.md](PLAN.md) for the design and [REVIEW.md](REVIEW.md) for the adversarial review (11 findings, all fixed — including an allocation-bomb in the container and broken HTML in `heat`).

## Why this, today

The ledger has compilers, databases, crypto, networking, ML and graphics — but nothing about *entropy coding*, the
one corner of computer science where information theory directly sets the price of every byte. Compression also
has the rare property of being fully self-checking: a codec is correct iff it round-trips, and it is good iff it
beats an independent reference (`gzip`, `bzip2`), so the whole project could be verified against ground truth.

## Where a human could take this next

- **Better CM**: bit-history state machines (PAQ's nonstationary states) instead of plain counters, a 2-layer mixer network, SSE chains, and dictionary preprocessing for text — worth another ~10%.
- **Speed**: SA-IS or divsufsort for the BWT; SIMD mixers; parallel BWT blocks; a `-j` flag.
- **Streaming**: the container is whole-file; add framed blocks so multi-GB inputs and pipes work in bounded memory.
- **Archive mode**: directories, per-file method choice, dedup via content-defined chunking.
- **Format**: optional dictionaries, a trained-model "zstd-style" preset, parallel decode index, and a stable spec document.
- **Teaching UI**: animate LZ77 matches, the BWT matrix, and the mixer weights over time in the heat report.
