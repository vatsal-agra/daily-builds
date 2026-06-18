# Cinch — Plan

## Concept
**Cinch** is a from-scratch data-compression toolkit written in pure Python 3
(standard library only — no `zlib`, no third-party deps in the codecs). It
implements the real algorithms behind modern compressors, end to end:

1. **Canonical Huffman** entropy coding — bit-exact, with a compact serialized
   code-length header (the same trick `gzip` uses to ship its trees).
2. **LZ77** dictionary compression — a sliding window with a hash-chain match
   finder, emitting `(literal)` / `(length, distance)` tokens.
3. **DEFLATE-lite** — LZ77 *composed with* Huffman, using the genuine DEFLATE
   length/distance symbol alphabets with **extra bits**, two separate Huffman
   trees (literals+lengths, distances), wrapped in a checksummed container.
4. **Range coding** (arithmetic coding) with an **adaptive** order-0 and order-1
   model — a fundamentally different entropy coder that routinely beats Huffman
   on natural-language text because it is not limited to whole-bit code lengths.

Every compressed file is a real, self-describing container (magic, version,
method, original length, CRC-32). Decompression is verified by CRC, and the
whole thing is gated by round-trip equality on a corpus plus a differential
**ratio** comparison against the stdlib heavyweights (`zlib`, `bz2`, `lzma`)
— used only as an external yardstick, never inside our codecs.

## Why it's interesting
Compression is where information theory meets fiddly bit-level engineering.
You cannot bluff it: a single wrong bit and the whole file fails to round-trip,
so correctness is brutally falsifiable. It also spans two genuinely different
paradigms — **dictionary** coding (LZ77, exploiting repetition) and **entropy**
coding (Huffman/arithmetic, exploiting skew) — and the interesting part is
watching them compose. Nothing in the ledger touches compression; the closest
neighbours (SAT solvers, a SQL B+tree, autodiff) are a different world.

## Architecture
```
bitio.py       MSB-first BitWriter / BitReader over a bytearray
huffman.py     frequency -> length-limited code lengths -> canonical codes
               -> encode/decode; compact RLE code-length header
lz77.py        hash-chain sliding-window match finder -> tokens -> decode
deflate.py     LZ77 tokens -> DEFLATE length/dist symbols (+extra bits)
               -> two canonical Huffman trees -> bitstream -> inverse
rangecoder.py  Subbotin-style 32-bit range coder + adaptive freq models
               (order-0 byte model, order-1 context model)
container.py   header (magic/version/method/origlen/CRC32) + dispatch:
               store / huffman / lz77 / deflate / range0 / range1
corpus.py      built-in test corpus generators (text, source, binary, edge)
cli.py         compress / decompress / bench / inspect / roundtrip / viz / demo
viz.py         emits a single self-contained HTML visualizer
tests.py       unit + property + differential test suite
demo.sh        end-to-end runnable demonstration
```

## Features

### Required (must fully work, no stubs)
1. **Canonical Huffman codec** — build optimal prefix code from byte
   frequencies, length-limit it, assign canonical codes, serialize the tree as
   a compact code-length table, and losslessly encode/decode arbitrary bytes.
2. **LZ77 sliding-window codec** — hash-chain match finder over a configurable
   window/lookahead producing literal/match tokens, with an exact decoder
   (including overlapping copies, e.g. RLE-style `aaaaaa`).
3. **DEFLATE-lite combined codec** — compose LZ77 + Huffman using the real
   DEFLATE length/distance code alphabets with extra bits and two Huffman
   trees, all inside a CRC-checked container file.
4. **CLI with verified round-trips** — `compress`/`decompress` real files,
   auto-selecting or forcing a method, plus `bench` that compresses a corpus
   with every method and reports ratio + speed, each verified by round-trip
   and CRC.

### Stretch
5. **Adaptive range coder** — order-0 and order-1 arithmetic coding with
   incremental frequency models; beats Huffman on text, demonstrated in `bench`.
6. **Interactive HTML visualizer** — a self-contained page that animates the
   LZ77 sliding window matching over a sample string and draws the Huffman tree
   with each symbol's code.
7. **`inspect`** — decode and pretty-print any Cinch container's header/stats
   without decompressing the whole payload, plus a per-method ratio leaderboard
   vs `zlib`/`bz2`/`lzma`.

## Verification strategy
- **Round-trip property**: every method, over a corpus including empty input,
  a single byte, all-identical bytes, random bytes, English text, source code,
  and structured/binary data — decompress(compress(x)) == x, byte for byte.
- **CRC integrity**: container stores CRC-32 of the original; decompress checks
  it and refuses corrupt data.
- **Canonical-code invariants**: prefix-free, Kraft sum <= 1, lengths within
  the limit, codes match a from-scratch re-derivation.
- **Differential ratio**: Cinch vs `zlib`/`bz2`/`lzma` — we don't have to win,
  but DEFLATE-lite must land in a sane neighbourhood of `zlib`, and range-1
  must beat our own Huffman on text.
- **Adversarial fuzz**: thousands of random byte strings of random lengths
  round-tripped through every method.

## Done means
All 6 phases pass their gates: 4 required + >=1 stretch fully working, an
adversarial review with every found bug fixed, a green test suite exercising
every feature, and a shippable README.
