# Spectral

A from-scratch JPEG image codec in pure Python — the Discrete Cosine
Transform, perceptual quantization, and Huffman entropy coding that turn
a bitmap into the `.jpg` files the entire internet is made of. Both
baseline and progressive output are verified against a real, independent
decoder: headless Chromium, via its own built-in `<img>` JPEG decoder,
checked pixel-for-pixel against Spectral's own decoder.

**Status: Phase 4 (stretch features + polish) complete.** All 4 required
features plus both planned stretch features are implemented, tested, and
independently verified. See [PLAN.md](PLAN.md) for the architecture/
feature list and [REVIEW.md](REVIEW.md) for the full adversarial-review
writeup (Phase 3 + a Phase 4 addendum).

## Quick start

```
python3 -m spectral.cli encode --test-image photo --width 96 --height 96 \
    --output out.jpg --quality 80 --subsampling 420
python3 -m spectral.cli decode out.jpg --output out.bmp

# progressive (SOF2): DC successive approximation + AC spectral selection
python3 -m spectral.cli encode --test-image photo --width 96 --height 96 \
    --output out_prog.jpg --quality 80 --progressive
python3 -m spectral.cli decode out_prog.jpg --output out_prog.bmp

python3 -m spectral.cli compare --test-image photo --qualities 10 50 90
python3 -m spectral.cli dct-demo
python3 -m spectral.cli viz --output viz.html   # interactive rate-distortion visualizer
./demo.sh
```

## Required features

- **Color pipeline**: RGB↔YCbCr (ITU-R BT.601 full range), box-filter
  chroma subsampling (4:4:4/4:2:2/4:2:0), bilinear chroma upsampling.
- **Block transform + quantization**: real separable 8×8 DCT-II/DCT-III
  (proven identical to a brute-force O(N⁴) reference transform), Annex-K
  quantization tables scaled 1–100, zigzag reordering.
- **Real JFIF bitstream (encode)**: full baseline sequential encoder —
  DC-differential + AC run-length + canonical Huffman (standard Annex-K
  tables, or optimized per-image tables built from real symbol
  frequencies), byte-stuffed bitstream, correct marker segments.
- **Full decoder**: the complete inverse pipeline, round-tripping to a
  visually-correct image, with clean errors (never a raw traceback) on
  truncated or corrupt input.

## Stretch features

- **Progressive JPEG (SOF2)**: DC successive approximation (2 scans: a
  coarse first pass + a literal raw-bit refinement pass, ITU-T T.81
  G.1.2.1) and AC spectral selection (2 non-interleaved bands per
  component). 8 real scans, a genuine coarse-to-fine visual reveal.
  *(AC successive approximation itself — as opposed to spectral
  selection — was not implemented; see REVIEW.md's Phase 4 addendum for
  the honest scope note.)*
- **Interactive rate-distortion visualizer** (`spectral.cli viz`): a
  self-contained HTML page where every image shown is a real
  Spectral-encoded `data:image/jpeg;base64,...` URI, rendered by the
  viewer's own browser — a quality slider, hand-rolled SVG rate-
  distortion curves (size and PSNR vs. quality, all 3 subsampling
  modes), a subsampling side-by-side comparison, and a progressive
  scan-by-scan reveal (each frame is a real file: the progressive output
  truncated after that scan and re-terminated with EOI, independently
  confirmed to decode correctly in headless Chromium).

## Verification

65/65 independent-oracle checks pass: every encoded JPEG (baseline: 3
subsampling modes × 3 quality levels × 5 test images; progressive: 3
subsampling×quality combinations × 5 test images) opens correctly in
real headless Chromium with zero console errors, and its decoded pixels
agree with Spectral's own decoder to within a few levels — see
`demo.sh` section 7 and `tests/browser_oracle_test.cjs`.

101/101 unit tests green, including permanent bit-flip fuzz regression
sweeps for both codecs and full CLI-level test coverage. Adversarial
review (Phase 3) found and fixed a critical decoder bug — an unvalidated
assumption about component geometry that a corrupted file could violate,
caught by a 9,600-trial fuzz sweep — plus 7 more real issues; see
[REVIEW.md](REVIEW.md) for the complete writeup, including what was
checked and ruled out as *not* a bug (bounded via Parseval's theorem and
cross-checking against the independent brute-force DCT oracle).

Remaining phases: verification (a dedicated test/demo pass — already
substantially covered by the above, but not yet formally closed out) and
shipping (final README polish + LEDGER.md entry).
