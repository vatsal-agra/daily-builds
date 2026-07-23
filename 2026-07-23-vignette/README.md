# Vignette

A from-scratch, pure-Python (stdlib only — no PIL, no numpy) baseline
JPEG-style lossy image codec: the transform-coding pipeline — DCT,
quantization, Huffman entropy coding — that underlies real-world image and
video compression, implemented by hand down to real, spec-valid `.jpg`
file bytes that any standard image viewer, browser, or the `file`/
`identify` utility recognizes as a genuine JPEG.

```
RGB → YCbCr → 4:2:0 chroma subsampling → 8×8 block DCT → quantization
  → zigzag scan → DC DPCM + AC run-length → Huffman entropy coding
  → real JFIF marker-framed bytes
```
and the full inverse, from bytes back to pixels.

## Why this one, today

Every previous daily build that touched compression did *lossless* general
coding (Huffman/LZ77/BWT), or built a *lossy 3D renderer*, or did
lossless-only image analysis — none of them implement **transform
coding**: turning spatial pixel blocks into frequency coefficients,
discarding the perceptually unimportant high-frequency ones via
quantization, and entropy-coding what's left. That's the actual idea that
makes JPEG, MPEG, and effectively every modern image/video/audio codec
possible, and it's satisfying to verify end-to-end: the DCT is provably
orthogonal (testable against a brute-force reference), and the output
format is a real, published international standard (ITU-T T.81) — so
"did I get it right" has an objective, external answer (the system `file`
utility independently recognizes the output as a real baseline JPEG),
not just "does it look plausible."

## Quick start

```
cd 2026-07-23-vignette
python3 -m unittest discover -s tests -v   # 50 tests, all green
./demo.sh                                  # full CLI walkthrough + verification

python3 -m vignette.cli encode gradient out/gradient.jpg -q 75
python3 -m vignette.cli decode out/gradient.jpg out/gradient.png
python3 -m vignette.cli analyze circles --qualities 95 75 50 25 10
python3 -m vignette.cli report out/report.html     # interactive quality-slider report
python3 -m vignette.cli gallery out/gallery.html    # quality-ladder artifact gallery
```

`encode`/`analyze`/`compare` accept either a built-in procedural test image
name (`gradient`, `checkerboard`, `circles`, `plasma`, `textbars` —
generated deterministically, so the whole pipeline is testable with zero
external image files) or a path to a binary PPM (P6) file.

No dependencies beyond the Python 3 standard library.

## Feature list

**Required (all four fully implemented, no stubs):**

1. **Real baseline JPEG encoder** (`vignette/encoder.py`) — the complete
   pipeline down to spec-valid marker-framed `.jpg` bytes: correct
   MCU/block padding for arbitrary (non-multiple-of-16) image sizes, the
   real ITU-T Annex K standard quantization tables scaled by the IJG
   quality formula, zigzag scan, DC delta + AC run-length encoding, and
   Huffman coding with correct 0xFF00 byte-stuffing. Independently
   verified as a real JPEG by the system `file` utility.
2. **Full baseline JPEG decoder** (`vignette/decoder.py`) — parses real
   marker segments from scratch (SOI/APP0/DQT/SOF0/DHT/SOS/EOI),
   Huffman-decodes the entropy stream, dequantizes, inverse-DCTs,
   upsamples chroma, and converts back to RGB — general enough to handle
   any 1×/2× H/V sampling factors a baseline-sequential encoder might use.
3. **Quality/rate-distortion analysis toolkit** (`vignette/metrics.py`,
   `cli.py analyze`) — PSNR, a windowed SSIM, compression ratio, and
   bits-per-pixel, swept across a quality range.
4. **Interactive HTML report** (`vignette/visualize.py`, `cli.py report`)
   — a self-contained page per test image with a live quality slider
   (size/PSNR/SSIM readouts), a 6×-zoom panel showing real 8×8 blocking
   artifacts at low quality, and a DCT-coefficient magnitude heatmap.

**Stretch (both implemented):**

5. **Optimal per-image Huffman tables** (`encode --optimal-huffman`) —
   real symbol-frequency-driven canonical Huffman tables (still a
   spec-legal custom DHT segment) instead of the fixed standard ones.
   Verified lossless relative to the standard-table encode at the same
   quality (bit-identical reconstructed pixels) while being meaningfully
   smaller (~19–25% on the test images).
6. **Quality-ladder artifact gallery** (`cli.py gallery`) — every test
   image rendered across a quality ladder from 100 down to 1, annotated
   with size/ratio/PSNR per step, visually demonstrating the classic JPEG
   artifact progression (blocking → ringing → chroma bleed).

## Process notes

- [PLAN.md](./PLAN.md) — architecture and original feature plan.
- [REVIEW.md](./REVIEW.md) — the adversarial-review pass: a critical
  quantization-table natural-order/zigzag-order indexing bug (invisible
  at quality 100, corrupted everything else — caught by testing a quality
  *sweep* instead of one happy-path setting), an HTML-report CSS layout
  bug, and a CLI error-handling gap were all found and fixed, with
  regression tests added so they can't silently come back.
- `tests/` — 50 unit tests (DCT correctness vs. a brute-force reference,
  Huffman prefix-freedom and byte-stuffing, PNG structural correctness,
  metrics sanity, and full codec round-trips across every test image,
  quality, and a battery of edge cases).
- `demo.sh` — runs the whole suite plus a live CLI walkthrough of every
  feature, including the `file`-utility cross-check and error-handling
  verification.

## Where a human could take this next

- **Progressive JPEG** (SOF2: spectral selection + successive
  approximation) — the encoder/decoder architecture here is baseline
  sequential only; progressive is a genuinely different scan structure.
- **Chroma upsampling quality** — the decoder currently uses nearest-
  neighbor chroma upsampling (simplest legal baseline behavior); real
  decoders often use bilinear or edge-directed upsampling for less
  visible color bleed.
- **Restart markers (DRI/RSTn)** for error-resilient streaming decode,
  and support for decoding arbitrary real-world JPEGs in general (this
  decoder handles what this encoder produces, plus the common baseline
  case — a from-scratch arithmetic-coding variant, 12-bit precision, or
  4-component CMYK support would widen real-world compatibility).
- **Speed** — the DCT/IDCT here are the direct O(N²)-per-axis separable
  sum-of-cosines definition in pure Python; a real implementation would
  use a fast (AAN or Loeffler) 8-point DCT algorithm and/or drop to
  numpy/C for the inner loops, which would make encoding video-rate
  or high-resolution images practical.
- **Perceptual tuning** — custom quantization tables tuned by actual
  human visual system contrast-sensitivity data (rather than reusing the
  1990s-era Annex K tables) would improve real quality-per-bit.
