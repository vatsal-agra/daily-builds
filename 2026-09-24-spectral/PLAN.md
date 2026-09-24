# Spectral — a from-scratch JPEG image codec

## Concept

Every prior "compression" build in this repo (Cinch, Shannon) implemented
**lossless, generic-byte** compression: Huffman, LZ77, arithmetic coding,
BWT — algorithms that treat input as an opaque byte stream and must
reconstruct it exactly. None of them ever transforms the *signal itself*.

JPEG is a different animal entirely: it's **lossy transform coding**. It
exploits the specific statistics of natural images and human visual
perception — convert to a luma/chroma color space so chroma can be thrown
away more aggressively than luma (we see brightness detail far better than
color detail), chop the image into 8×8 blocks, run each block through the
**Discrete Cosine Transform** to move energy from spatial pixels into a
handful of low-frequency coefficients, **quantize** those coefficients
(divide by a perceptually-tuned table and round — this step is where the
information is actually thrown away, and it is irreversible), then
losslessly entropy-code what's left with Huffman. The decoder runs the
reversible half of that pipeline backwards (Huffman decode → dequantize →
inverse DCT → color convert) and gets back an image that is *not* bit-exact
but is visually close, at a fraction of the storage a lossless coder could
ever achieve. This is a genuinely new domain for the repo: frequency-domain
transforms, perceptual quantization, and a real interchange file format
(JFIF/JPEG) that has to be byte-for-byte spec-compliant enough that a
totally independent decoder — a real web browser's built-in JPEG decoder,
via headless Chromium — accepts it and renders the right picture. That's
the correctness oracle no other project in this repo has had available:
an external, already-correct, never-modified reference decoder to check
our own bitstream against, blind to how we built it.

## Architecture

```
spectral/
  colorspace.py     RGB <-> YCbCr (ITU-R BT.601 full-range), chroma
                     subsampling/upsampling (4:4:4, 4:2:2, 4:2:0)
  dct.py             8x8 forward/inverse DCT-II (separable, precomputed
                     cosine basis), plus a brute-force O(N^4) reference
                     2D DCT used only by tests to prove the fast one is
                     the same transform
  quant.py           Annex-K standard luma/chroma quantization tables,
                     quality-factor scaling (IJG formula), zigzag order
  bitstream.py       MSB-first bit writer/reader with JPEG 0xFF00 byte
                     stuffing and marker-aware resync
  huffman.py         canonical Huffman: build code tables from JPEG's
                     BITS/HUFFVAL representation (both the Annex-K default
                     tables AND an *optimized* per-image table built from
                     real symbol frequencies), encode/decode
  markers.py         JFIF/JPEG marker segment writers and a tolerant
                     parser (SOI/APP0/DQT/SOF0/SOF2/DHT/SOS/DRI/EOI)
  encoder.py         full baseline (SOF0) sequential JPEG encoder:
                     block split -> level shift -> DCT -> quantize ->
                     zigzag -> DC-diff + AC run-length -> Huffman ->
                     valid JFIF bytes
  decoder.py         full baseline decoder: the exact inverse pipeline,
                     tolerant of truncated/corrupt input with clean errors
  progressive.py     progressive (SOF2) encode/decode: DC-first scan +
                     multiple AC spectral-selection/successive-approximation
                     scans, so the image reveals coarse-to-fine over
                     several passes
  bmp.py             trivial uncompressed BMP reader/writer (real pixel
                     I/O with zero compression, so we always have a
                     ground-truth lossless image to encode from and
                     compare against)
  png_reader.py      minimal PNG decoder (filters hand-written; only
                     `zlib.decompress` is used, never for anything in the
                     JPEG codec path) so real PNG test images can be
                     loaded as encoder input
  testimages.py      procedural synthetic test images (smooth gradients,
                     sharp edges/checkerboards, radial targets, synthetic
                     "photo-like" scenes mixing smooth regions + edges +
                     noise) so the suite is fully self-contained
  metrics.py         MSE/PSNR/compression-ratio, used both by tests and
                     by the rate-distortion visualizer
  cli.py             `encode/decode/compare/dct-demo/rd-curve/viz/demo`
  viz.py             generates a self-contained interactive HTML page
tests/               unit + property + differential test suite
demo.sh              end-to-end walkthrough, including a real
                     headless-Chromium round-trip against our own output
```

## Why an external oracle matters here

This repo's own postmortems (Vein's transcribed secp256k1 `Gy` constant,
wrong in a hand-typed "known-good" vector too) show that hand-transcribing
spec tables is exactly the kind of bug that survives a whole test suite
because the test suite was written by the same person who mistyped the
table. JPEG's Annex-K tables are exactly that risk. The mitigation:
Chromium's `<img>` decoder was written by a completely different team from
a completely different codebase and has never seen a line of this repo's
code. If it renders our `.jpg` bytes correctly, our marker structure,
Huffman tables, and bitstream packing are genuinely spec-compliant — not
just self-consistent.

## Feature list

**Required (4):**
1. **Color pipeline** — RGB↔YCbCr conversion and 4:4:4/4:2:2/4:2:0 chroma
   subsampling/upsampling, energy-preserving within JPEG's own definition
   (round-trip RGB→YCbCr→RGB is near-identity; subsampled chroma
   reconstructs close to the pre-subsample values).
2. **Block transform + quantization** — real 8×8 DCT-II (forward + inverse)
   proven identical to a brute-force reference transform, plus Annex-K
   quantization tables scaled by a 1–100 quality factor and zigzag
   reordering, demonstrably trading file size for PSNR as quality changes.
3. **Real JFIF bitstream (encode)** — full baseline sequential encoder
   (DC differential + AC run-length + Huffman, byte-stuffed bitstream,
   correct marker segments) producing files a real, independent decoder
   (headless Chromium) opens and renders correctly.
4. **Full decoder** — the complete inverse pipeline (parse markers →
   Huffman decode → dequantize → IDCT → upsample → YCbCr→RGB), round-
   tripping our own encoder's output to a visually-correct image within a
   measured PSNR bound, and failing cleanly (no traceback) on truncated
   or corrupt input.

**Stretch (2+):**
5. **Progressive JPEG** (SOF2: DC-first scan, then multiple AC
   spectral-selection + successive-approximation scans) — a materially
   different bitstream structure from baseline, also independently
   verified by Chromium.
6. **Interactive rate-distortion visualizer** — a self-contained HTML page
   embedding real encoder output at multiple quality levels as actual
   `data:image/jpeg;base64,...` images (so the *browser itself* is the
   viewer, proving the bytes are real JPEG, not a picture of one), a
   quality-vs-size-vs-PSNR curve, a subsampling-mode comparison, a
   zoomable block-artifact view, and (if progressive ships) a
   scan-by-scan coarse-to-fine reveal.

If any required feature proves infeasible it will be replaced with one of
equal size and that substitution will be documented in REVIEW.md — not
silently dropped.
