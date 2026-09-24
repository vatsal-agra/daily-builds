# Spectral

A from-scratch JPEG image codec in pure Python — the Discrete Cosine
Transform, perceptual quantization, and Huffman entropy coding that turn
a bitmap into the `.jpg` files the entire internet is made of. Output is
verified against a real, independent decoder: headless Chromium, via its
own built-in `<img>` JPEG decoder, checked pixel-for-pixel against
Spectral's own decoder.

**Status: Phase 3 (adversarial review) complete.** All 4 required
features work end-to-end and have survived a hostile review pass —
9,600-trial bit-flip fuzzing, direct CLI probing, and mathematical
bound-checking of the entropy coder — with every real bug found and
fixed. See [PLAN.md](PLAN.md) for the architecture/feature list and
[REVIEW.md](REVIEW.md) for the full review writeup.

## Quick start

```
python3 -m spectral.cli encode --test-image photo --width 96 --height 96 \
    --output out.jpg --quality 80 --subsampling 420
python3 -m spectral.cli decode out.jpg --output out.bmp
python3 -m spectral.cli compare --test-image photo --qualities 10 50 90
python3 -m spectral.cli dct-demo
./demo.sh
```

## What's implemented so far

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

45/45 independent-oracle checks pass: every encoded JPEG (3 subsampling
modes × 3 quality levels × 5 test images) opens correctly in real headless
Chromium with zero console errors, and its decoded pixels agree with
Spectral's own decoder to within a few levels — see `demo.sh` section 6
and `tests/browser_oracle_test.cjs`.

**Chroma upsampling is bilinear** (upgraded from nearest-neighbor during
review — smoother output and measurably closer to a real decoder's
reconstruction). See [REVIEW.md](REVIEW.md) for what that comparison
found and fixed, including a critical decoder bug (an unvalidated
assumption about component geometry that a corrupted file could violate)
caught by a 9,600-trial bit-flip fuzz sweep.

Stretch features (progressive JPEG, interactive rate-distortion
visualizer) and final polish are next.
