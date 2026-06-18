# Shannon — a from-scratch compression toolkit

## Concept
**Shannon** is a lossless data-compression toolkit built from first principles in
pure Python (stdlib only). It implements the three pillars of real-world
compressors — **entropy coding**, **dictionary/LZ coding**, and
**reversible transforms** — and composes them into complete, named codecs that
read and write a real container format with integrity checks. Every codec is
proven correct by **round-trip equality** (`decompress(compress(x)) == x`) over
fuzzed and real inputs, and benchmarked against the **Shannon entropy bound**.

## Why it's interesting
Compression is where information theory meets bit-twiddling engineering. A single
project naturally contains:
- A **Huffman coder** (canonical codes, bit-level I/O).
- An **arithmetic/range coder** with adaptive probability models — the thing that
  beats Huffman and is famously fiddly to get exactly reversible.
- **LZ77/LZSS** sliding-window dictionary matching.
- The **Burrows–Wheeler Transform** (the magic behind bzip2) with a real
  suffix-array construction, plus **Move-To-Front** and **RLE**.

These are combined into bzip2-style and DEFLATE-style pipelines. The round-trip
property is a *perfect* oracle: any bug shows up instantly as a mismatch, so the
verification story is unusually strong. It also has genuinely nice things to
visualize: a Huffman tree, the BWT rotation matrix, LZ77 match arrows.

## Architecture
```
shannon/
  bitio.py        # BitWriter / BitReader — MSB-first bit streams
  entropy.py      # Shannon entropy, per-symbol stats, model helpers
  huffman.py      # canonical Huffman build + encode/decode
  arith.py        # range coder + order-0 / order-1 adaptive models
  lz77.py         # LZSS sliding-window matcher + token stream
  transforms.py   # BWT (suffix array) + inverse, MTF, RLE
  codecs.py       # named end-to-end codecs over a .shz container
  container.py    # .shz format: magic, method, checksum, framing
  analyze.py      # entropy report / codec comparison table
  viz.py          # generates a self-contained interactive HTML report
cli.py            # `shannon` command-line front end
tests/            # round-trip, oracle, and unit tests
demo.sh           # exercises every feature end to end
```

Data flow for a codec, e.g. `bwt` (bzip2-lite):
```
bytes -> BWT -> MTF -> RLE -> Huffman -> .shz container
```
and exactly the inverse on the way back out.

## Container format `.shz`
`magic(4) | version(1) | method(1) | orig_len(varint) | crc32(4) | payload`
- `crc32` of the original data is stored so decompression self-verifies.
- `method` selects the codec; unknown methods raise a clean error.

## Feature list

### Required (must fully work)
1. **Huffman codec** — canonical Huffman codes with a correct bit-level writer/
   reader; handles the single-symbol and empty-input edge cases; round-trips.
2. **Arithmetic (range) coder** — carry-correct 32-bit range coder with an
   adaptive order-0 model *and* an order-1 (previous-byte context) model; this is
   the hard-to-get-right centerpiece; round-trips bit-exactly.
3. **LZ77/LZSS dictionary coder** — sliding-window longest-match search emitting
   (literal | back-reference) tokens, with a back-reference + Huffman backend
   ("deflate-lite"); round-trips.
4. **BWT pipeline** — Burrows–Wheeler Transform via suffix array + correct inverse
   (LF-mapping), composed with Move-To-Front and RLE into a "bzip-lite" codec;
   round-trips.

### Stretch
5. **Entropy analyzer + comparison report** — computes order-0/order-1 entropy of
   an input and prints a table comparing every codec's real ratio against the
   theoretical bound (and picks the winner). A `--best` auto mode encodes with the
   smallest-output codec.
6. **Interactive HTML visualizer** — a self-contained (no-deps) HTML page
   rendering the Huffman tree for an input, the BWT rotation matrix + transformed
   string, and an LZ77 match map — generated straight from the real engine output.

### Extra glue (still real, still tested)
- A unified **`.shz` container** with CRC self-check and a tolerant decoder.
- A **CLI** (`compress`/`decompress`/`analyze`/`bench`/`viz`/`demo`) with sane
  errors and SAT-style exit codes.

## Verification strategy
- **Round-trip gate:** every codec must satisfy `decode(encode(x)) == x` for: empty
  input, single byte, single repeated symbol, random bytes, structured text,
  and a fuzz sweep of thousands of random inputs of varied length/alphabet.
- **Oracle checks:** Huffman code lengths satisfy Kraft equality; arithmetic-coder
  output length is within a small constant of the order-N entropy; BWT inverse is
  the exact identity; CRC mismatch is detected.
- **Comparison sanity:** on text, arithmetic-o1 and bwt should both beat raw;
  on random bytes, no codec should expand by more than container overhead.
