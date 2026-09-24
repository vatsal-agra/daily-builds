# Spectral

A from-scratch JPEG image codec in pure Python — the Discrete Cosine
Transform, perceptual quantization, and Huffman entropy coding that turn
a bitmap into the `.jpg` files the entire internet is made of. Both
baseline and progressive output are verified against a real, independent
decoder — headless Chromium's own built-in JPEG decoder — checked
pixel-for-pixel against Spectral's own decoder, not just "does it open."

**Status: shipped.** All 4 required features plus both planned stretch
features are implemented, tested, and independently verified.

## What it is

Every JPEG in existence is the output of the same pipeline: convert an
image to a luma/chroma color space, throw away color resolution more
aggressively than brightness resolution (because human vision does the
same), chop it into 8×8 blocks, run each block through the Discrete
Cosine Transform to concentrate its energy into a handful of low-
frequency coefficients, quantize those coefficients against a
perceptually-tuned table (the one genuinely *lossy*, irreversible step),
and Huffman-code what's left. Spectral implements that entire pipeline
from first principles — no `PIL`, no `libjpeg`, no `zlib`-as-a-codec, not
even a borrowed quantization constant that wasn't independently
re-derived and checked — and produces byte streams real, unmodified
JPEG decoders (Chromium's, tested; any conformant one, by construction)
accept and render correctly.

## How to run it

```bash
# baseline JPEG
python3 -m spectral.cli encode --test-image photo --width 96 --height 96 \
    --output out.jpg --quality 80 --subsampling 420
python3 -m spectral.cli decode out.jpg --output out.bmp

# progressive JPEG (SOF2): DC successive approximation + AC spectral selection
python3 -m spectral.cli encode --test-image photo --width 96 --height 96 \
    --output out_prog.jpg --quality 80 --progressive
python3 -m spectral.cli decode out_prog.jpg --output out_prog.bmp

# your own image (BMP or PNG in, JPEG out)
python3 -m spectral.cli encode --input photo.png --output photo.jpg --quality 85

# rate-distortion sweep, DCT correctness proof, interactive visualizer
python3 -m spectral.cli compare --test-image photo --qualities 10 50 90
python3 -m spectral.cli dct-demo
python3 -m spectral.cli viz --output viz.html   # open it in a browser

# everything above, plus the full test suite and the Chromium oracle check
./demo.sh
```

No dependencies beyond the Python 3 standard library for the codec
itself. `demo.sh`'s independent-oracle section uses the environment's
pre-installed headless Chromium via Playwright (Node) — it's skipped
gracefully if Node isn't on `PATH`.

## Full feature list

**Required:**
1. **Color pipeline** — RGB↔YCbCr (ITU-R BT.601, full range), box-filter
   chroma subsampling (4:4:4/4:2:2/4:2:0), bilinear chroma upsampling.
2. **Block transform + quantization** — a real separable 8×8 DCT-II
   (forward) / DCT-III (inverse), proven identical to an independent
   brute-force O(N⁴) reference transform to 1e-8; ITU-T T.81 Annex K
   quantization tables scaled for quality 1–100 via the IJG formula;
   zigzag reordering.
3. **Real JFIF bitstream (encode)** — a full baseline sequential
   encoder: DC-differential + AC run-length coding, canonical Huffman
   (standard Annex-K tables, or genuinely optimized per-image tables
   built from measured symbol frequencies via a real Huffman-tree
   construction with a tested length-limiting fallback), byte-stuffed
   bitstream, correct marker segments (SOI/APP0/DQT/SOF0/DHT/SOS/EOI).
4. **Full decoder** — the complete inverse pipeline (parse → Huffman
   decode → dequantize → IDCT → chroma upsample → YCbCr→RGB), with
   clean, specific errors (never a raw traceback) on truncated, corrupt,
   or adversarially-crafted input.

**Stretch (both shipped):**
5. **Progressive JPEG (SOF2)** — DC successive approximation (a coarse
   first scan + a literal raw-bit refinement pass, ITU-T T.81 G.1.2.1)
   and AC spectral selection (2 non-interleaved bands per component, 6
   AC scans + 2 DC scans = 8 scans total). A real, materially different
   bitstream structure from baseline, independently decodable at every
   scan boundary. *(AC successive approximation specifically — as
   opposed to spectral selection — was not implemented; a deliberate,
   disclosed scope reduction, see REVIEW.md.)*
6. **Interactive rate-distortion visualizer** (`spectral.cli viz`) — a
   self-contained HTML page where every image is a real
   `data:image/jpeg;base64,...` URI of actual encoder output, rendered
   by the viewer's own browser: a quality slider, hand-rolled SVG
   rate-distortion curves (size and PSNR vs. quality, all 3 subsampling
   modes), a subsampling side-by-side comparison, and a progressive
   scan-by-scan reveal where each frame is a genuinely independent,
   valid JPEG file (the real progressive output truncated after that
   scan and re-terminated with an EOI marker).

**Supporting infrastructure:** a hand-rolled uncompressed-BMP reader/
writer; a minimal PNG reader (filter reconstruction is hand-written; only
`zlib.decompress` is used, and never on the JPEG codec path) so real PNG
images can be loaded as encoder input; 5 procedural synthetic test-image
generators so the whole suite is reproducible with no external assets;
PSNR/compression-ratio metrics.

## Why this, today

Every prior compression project in this repo (`2026-06-17-cinch`,
`2026-06-17-shannon`) implemented **lossless, generic-byte** compression
— Huffman, LZ77, arithmetic coding, BWT — algorithms that treat their
input as an opaque byte stream. JPEG is a genuinely different problem:
**lossy transform coding** that exploits the specific statistics of
natural images and human visual perception, where the interesting
engineering is in a frequency-domain transform and a deliberate,
irreversible information-discarding step, not in reconstructing input
exactly. It also came with an unusually strong correctness oracle no
earlier project in this repo had available: a real, already-correct,
completely independent decoder (a web browser) that either renders a
produced file correctly or doesn't — no partial credit, no ambiguity
about what "correct" means. That oracle earned its keep immediately: it
caught two real, otherwise-invisible bugs (see REVIEW.md), including one
in a from-scratch DCT reference implementation whose own docstring
already warned about exactly the transcription-error risk it turned out
to have.

## Where a human could take this next

- **AC successive approximation** — the one deliberately-descoped piece
  of the progressive plan. `progressive.py`'s module docstring and
  REVIEW.md's Phase 4 addendum lay out exactly what it needs (T.81
  G.1.2.3's correction-bit/EOB-run interleaving).
- **Restart markers / intervals (DRI/RST)** — would let the decoder
  accept arbitrary real-world JPEGs (e.g. from cameras) that use them;
  currently out of scope since Spectral's own encoder never emits them
  (see REVIEW.md's scope note).
- **Chroma upsampling parity with a specific reference decoder** —
  Spectral's bilinear filter is a genuine, correct interpolation, but
  matching one implementation's exact filter (e.g. libjpeg's "fancy"
  triangle-filter upsampling) bit-for-bit was explicitly not chased;
  doing so is a bounded, well-specified follow-up.
- **Arithmetic coding mode** — JPEG defines an (optional, patent-
  encumbered-in-its-era, now-expired) arithmetic entropy coder as an
  alternative to Huffman; `huffman.py`'s `HuffmanTable` abstraction was
  written narrowly enough that swapping in a QM-coder would touch
  `entropy.py`/`encoder.py`/`decoder.py` but not the DCT/quantization
  core.
- **Performance** — pure Python; a 256×256 image encodes/decodes in well
  under a second, but a NumPy-vectorized DCT/quantization path (the
  block loop is the obvious target) would be a substantial, self-
  contained speedup for anyone who wants this on real photos instead of
  test images.

## Verification

- **101/101 unit tests green** (`./demo.sh` section 1, or
  `python3 -m unittest discover -s tests`), including permanent bit-flip
  fuzz regression sweeps for both the baseline and progressive decoders,
  and full CLI-level test coverage (subprocess-driven, `tests/test_cli.py`).
- **65/65 independent-oracle checks pass**: every encoded JPEG (baseline:
  3 subsampling modes × 3 quality levels × 5 test images; progressive: 3
  subsampling/quality combinations × 5 test images) opens correctly in
  real headless Chromium with zero console errors, decoding to pixels
  that agree with Spectral's own decoder to within a few levels
  (`demo.sh` section 7, `tests/browser_oracle_test.cjs`).
- **`demo.sh`** runs all of the above plus a DCT-vs-brute-force-oracle
  proof, a full CLI walkthrough (synthetic image and a real BMP file,
  both Huffman table modes), a rate-distortion sweep, a progressive
  encode/decode round trip, CLI error-handling checks, and visualizer
  generation — 9 sections, ~30 seconds, exits clean.
- **Adversarial review** (REVIEW.md) found and fixed 8 real issues across
  Phases 3–4 via 13,200+ combined random bit-flip trials, direct CLI
  probing, and mathematical bound-checking — including one critical
  decoder bug (an unvalidated component-geometry assumption a corrupted
  file could violate, crashing deep inside plane reconstruction with an
  opaque `IndexError` before the fix) — plus a documented account of what
  was investigated and found to be *correct, expected behavior* rather
  than a bug (residual pixel divergence from Chromium, isolated to
  spec-permitted upsampling-filter and IDCT-rounding implementation
  choices, not an error in this codec).
