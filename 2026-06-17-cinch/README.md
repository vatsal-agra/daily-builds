# Cinch

A from-scratch **data-compression toolkit** in pure Python (standard library
only — no `zlib`/`bz2`/`lzma` inside any codec). Cinch implements the real
algorithms behind modern compressors, end to end, with a self-describing,
CRC-checked container format and a verified round-trip harness.

```
$ python3 cli.py bench
corpus                 size         store     huffman        lz77     deflate      range0      range1      zlib-9       bz2-9        lzma
-----------------------------------------------------------------------------------------------------------------------------------------
all-same               4000         1.003       0.131       0.017       0.011       0.009       0.009       0.007       0.011       0.023
english               17498         1.001       0.509       0.450       0.320       0.504       0.325       0.313       0.220       0.291
source-code           17666         1.001       0.555       0.116       0.095       0.552       0.274       0.088       0.066       0.084
repetitive            20000         1.001       0.651       0.015       0.013       0.639       0.050       0.007       0.009       0.008
random                 8000         1.002       1.009       1.128       1.011       1.024       1.116       1.001       1.061       1.008
        (values are compressed/original ratio — lower is better; every Cinch result is round-trip + CRC verified)
```

## What it is

Five real compressors, each usable on its own and all reachable through one
container/CLI:

| method    | family            | what it does |
|-----------|-------------------|--------------|
| `store`   | none              | raw bytes (the floor — `auto` never does worse than this + ~12 B) |
| `huffman` | entropy           | canonical Huffman with length-limited (package-merge) optimal codes |
| `lz77`    | dictionary        | sliding-window hash-chain match finder with lazy matching |
| `deflate` | dictionary+entropy| **LZ77 ∘ Huffman** with the real DEFLATE length/distance symbol alphabets + extra bits and two dynamic Huffman trees |
| `range0`  | entropy (arithmetic) | adaptive **order-0** range coder |
| `range1`  | entropy (arithmetic) | adaptive **order-1** (context = previous byte) range coder |

Pick one with `-m`, or let `-m auto` try them all and keep the smallest.

## How to run

No installation, no dependencies — Python 3.8+.

```bash
# Compression-ratio leaderboard vs the stdlib heavyweights
python3 cli.py bench

# Verify every method round-trips on a real file (with timings)
python3 cli.py roundtrip path/to/file

# Compress / inspect / decompress  (-> file.cinch and back)
python3 cli.py compress path/to/file -m auto
python3 cli.py inspect  path/to/file.cinch
python3 cli.py decompress path/to/file.cinch -o restored

# Build the interactive HTML visualizer (LZ77 window + Huffman tree)
python3 cli.py viz --text "the quick brown fox the quick brown fox" -o cinch_viz.html

# Self-contained end-to-end demo
python3 cli.py demo
./demo.sh

# Tests (set CINCH_FUZZ=20000 for a heavy fuzz run)
python3 tests.py
```

## Feature list

**Required (all working, no stubs):**
1. **Canonical Huffman codec** — byte frequencies → length-limited optimal code
   lengths via the **package-merge** algorithm → canonical codes → bit-packed
   stream with an RLE'd code-length header. Verified optimal vs textbook Huffman.
2. **LZ77 sliding-window codec** — hash-chain match finder (32 KB window,
   3–258-byte matches) with one-step lazy matching; exact decoder including
   overlapping/run-style copies.
3. **DEFLATE-lite combined codec** — LZ77 tokens mapped onto the genuine DEFLATE
   length/distance code alphabets with extra bits, coded by two per-file dynamic
   Huffman trees, inside a CRC-checked container.
4. **CLI with verified round-trips** — `compress`/`decompress`/`bench`/
   `roundtrip`/`inspect`, every result round-trip- and CRC-verified.

**Stretch (all working):**
5. **Adaptive range (arithmetic) coder** — carryless 32-bit Subbotin coder with
   order-0 and order-1 models; order-1 beats our own Huffman on text.
6. **Interactive HTML visualizer** — a self-contained dark-themed page that
   animates the LZ77 sliding window (literals, back-references, copy source) and
   draws the canonical Huffman tree with every leaf's code.
7. **`inspect` + ratio leaderboard** — decode a container's header without
   decompressing, and benchmark every method against `zlib`/`bz2`/`lzma`.

**Engineering:**
- From-scratch CRC-32 (verified bit-identical to `zlib.crc32`).
- Self-describing container: magic, version, method, CRC, original length.
- Corrupt/truncated input is always rejected with a clean `CinchError` — never a
  raw exception and never a hang (see `REVIEW.md`, bug B5).

## Why I chose this today

The ledger was deep on solvers and engines (a world generator, a regex engine,
a SQL B+tree database, a Raft simulator, a physics engine, an autodiff engine,
and a long run of SAT solvers) but had **nothing on data compression** — a topic
that sits right at the meeting point of information theory and bit-level
engineering, and one that is *brutally* falsifiable: a single wrong bit and the
file simply won't round-trip. It also spans two genuinely different paradigms —
dictionary coding (LZ77) and entropy coding (Huffman, arithmetic) — and the most
interesting part is watching them compose into DEFLATE.

## Where a human could take this next

- **Speed:** the models and match finder are plain Python. A Fenwick-tree
  frequency model would make the range coder O(log n)/symbol; the LZ77 inner
  loop is the obvious Cython/Rust target.
- **Stronger models:** order-N / PPM with escape symbols, or a context-mixing
  (PAQ-style) model, would close the gap to `lzma` on text.
- **Bit-exact gzip:** emit the actual RFC 1951 bitstream (fixed + dynamic
  blocks, the real code-length code) so output is `gunzip`-compatible.
- **Streaming & large files:** block-based framing with independent windows so
  arbitrarily large inputs compress in bounded memory.
- **BWT branch:** a Burrows–Wheeler + MTF + RLE front end (the bzip2 family) to
  compare a third paradigm against the two implemented here.

## Files
```
bitio.py      MSB-first bit reader/writer
util.py       varint + from-scratch CRC-32
huffman.py    package-merge, canonical codes, decoder, Huffman codec
lz77.py       hash-chain match finder, tokenize/detokenize, LZ77 codec
deflate.py    DEFLATE length/distance alphabets, combined LZ77+Huffman codec
rangecoder.py Subbotin range coder + adaptive order-0/order-1 models
container.py  .cinch format, method dispatch, CRC, inspect
corpus.py     deterministic built-in test corpus
cli.py        command-line interface
viz.py        self-contained HTML visualizer generator
tests.py      unit + property + differential + fuzz suite
demo.sh       end-to-end demonstration
PLAN.md / REVIEW.md   plan and adversarial review
```
