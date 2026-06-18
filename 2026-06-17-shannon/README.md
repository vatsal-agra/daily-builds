# Shannon

A from-scratch lossless **data-compression toolkit** in pure Python (stdlib
only — no `zlib`/`bz2`/`lzma`, no third-party packages). Shannon implements the
three pillars of real compressors and composes them into named codecs over a
self-verifying container format. Every codec is proven correct by **round-trip
equality** and measured against the **Shannon entropy bound**.

![overview](docs/overview.png)

## What it is

Three families of technique, all hand-written:

| Family | Implementation |
|---|---|
| **Entropy coding** | Canonical **Huffman** (bit-exact, table-free decode) and a **Witten–Neal–Cleary arithmetic coder** with adaptive **order-0** and **order-1** (previous-byte context) models over a Fenwick-tree frequency table. |
| **Dictionary coding** | **LZ77/LZSS** sliding-window matching (32 KiB window, 3-byte hash chains) with a Huffman + gamma-coded token backend ("deflate-lite"). |
| **Reversible transforms** | **Burrows–Wheeler Transform** (suffix-array forward, LF-mapping inverse), **Move-To-Front**, and **run-length coding**, composed into a "bzip-lite" pipeline (BWT → MTF → RLE → Huffman). |

These are exposed as six codecs — `store`, `huffman`, `arith0`, `arith1`,
`lz77`, `bwt` — written into a `.shz` container with a magic header, the method
id, the original length, and a CRC-32 of the original data so **decompression
self-verifies**.

## How to run

No installation, no dependencies. Python 3.8+.

```sh
# compress, automatically picking the smallest codec
python3 cli.py compress PLAN.md --best          # -> PLAN.md.shz

# or choose a specific codec
python3 cli.py compress PLAN.md -m bwt -o out.shz

# inspect / restore (round-trip is byte-identical, CRC-checked)
python3 cli.py info       out.shz
python3 cli.py decompress out.shz -o restored.md

# entropy + codec comparison table
python3 cli.py analyze PLAN.md

# self-contained interactive HTML report (open in any browser)
python3 cli.py viz PLAN.md -o report.html

# self-checking demonstration and the full test suite
python3 cli.py demo
./demo.sh
python3 -m unittest discover -s tests
```

## Full feature list

**Required (all shipped):**
1. **Huffman codec** — optimal code lengths from a Huffman tree, canonical
   codeword assignment, MSB-first bit I/O; correct on empty / single-symbol
   inputs; satisfies Kraft equality.
2. **Arithmetic (range) coder** — 32-bit WNC coder with carry/underflow handling
   and adaptive order-0 *and* order-1 models; lands within a few percent of the
   entropy bound (≈ +2.5% over H₀ on PLAN.md).
3. **LZ77/LZSS dictionary coder** — greedy longest-match over a hash-chained
   sliding window, Huffman-coded literal/length/distance token streams.
4. **BWT pipeline** — suffix-array Burrows–Wheeler transform with sentinel,
   exact LF-mapping inverse, block-based (32 KiB) so it scales, plus MTF + RLE +
   Huffman.

**Stretch (shipped):**
5. **Entropy analyzer + comparison report** — order-0/order-1 entropy, ideal
   sizes, and a ranked table of every codec's real ratio vs the bound, with a
   winner and a `--best` auto-select mode.
6. **Interactive HTML visualizer** — a single self-contained file (inline
   CSS/JS, zero deps) with four tabs: codec comparison bars, the real canonical
   **Huffman tree**, the sorted **BWT rotation matrix**, and the **LZ77 token
   map**.

![huffman tree](docs/huffman-tree.png)
![lz77 tokens](docs/lz77-tokens.png)

**Engineering glue:** the `.shz` container with CRC self-check; a tolerant,
hardened decoder (rejects bad magic, corruption, and decompression bombs); a CLI
with sane errors and exit codes (0 ok / 1 usage / 2 corruption).

## Verification

- **28-test suite** (`tests/test_shannon.py`): per-module round-trips on edge
  inputs (empty, single byte, single symbol, all-256), Kraft equality,
  entropy-bound proximity, a known-vector BWT, a **1,000-case differential fuzz**
  across all codecs, a **corruption sweep** proving the decoder never crashes and
  never returns wrong data undetected, decompression-bomb rejection, and CLI
  end-to-end tests. All green.
- **`shannon demo`** asserts the headline claims live: arithmetic ≤ Huffman on
  text, order-1 < order-0 on text, LZ < entropy-only on repetitive data, and
  corruption/bomb detection.

## Why I chose this today

The build ledger had drifted into a long run of SAT solvers plus other
algorithm/engine projects, so I wanted a genuinely different domain. Compression
is a sweet spot: it sits exactly where information theory meets careful
bit-level engineering, it naturally yields a *family* of distinct, non-trivial
features (Huffman, arithmetic coding, LZ, BWT), and — crucially — the round-trip
property is a **perfect oracle**, so the correctness story can be unusually
strong rather than hand-wavy. It also has things genuinely worth visualizing.

## Where a human could take this next

- **Speed:** the BWT pipeline is the slow path (MTF is `O(256·n)` via list ops,
  and the suffix array is `O(n log²n)` in Python). A fixed-size MTF table and a
  linear-time SA (SA-IS / DC3), or a C extension, would make it competitive.
- **Better modeling:** a context-mixing / PPM model, or an order-2 arithmetic
  model, would beat `arith1`; an LZ backend that arithmetic-codes its tokens
  (instead of Huffman) would close the gap to real deflate/zstd.
- **Real format parity:** emit/consume actual gzip or bzip2 streams to
  cross-check against the system tools byte-for-byte.
- **Streaming + framing:** chunked streaming compression for inputs larger than
  memory, and per-block codec selection inside one archive.
- **The visualizer** could animate the arithmetic-coder interval shrinking and
  step the LZ window live.

## Layout
```
cli.py              CLI front end
shannon/
  bitio.py          MSB-first bit streams + varints
  entropy.py        H0 / H1 / ideal-size measurements
  huffman.py        canonical Huffman
  arith.py          arithmetic coder + adaptive models
  lz77.py           LZSS + Huffman backend
  transforms.py     BWT / MTF / RLE
  codecs.py         end-to-end codecs
  container.py      .shz format + integrity checks
  analyze.py        entropy + comparison report
  viz.py            interactive HTML report
  demo.py           self-checking demo
tests/test_shannon.py
demo.sh
```
