# Optic — Computer Vision from Scratch

## Concept
A complete, dependency-free computer vision library in pure Python 3 that implements
the classic algorithms every CV textbook covers — from raw pixel I/O all the way to
feature detection, morphological analysis, line detection, and template matching —
plus an interactive HTML pipeline visualizer.

## Why interesting
Computer vision is the one domain in this daily-build series that hasn't been touched.
Every algorithm here is a satisfying puzzle in its own right: Canny turns a noisy
grayscale image into a 1-pixel-wide edge map by combining Gaussian smoothing, gradient
estimation, non-maximum suppression, and hysteresis — three independent ideas that only
work together. Harris corners emerge from a 2×2 structure tensor and a scalar response
function. The Hough transform inverts the geometry problem (where are the lines?) into a
voting problem (which parameters accumulate the most votes?). Each algorithm is both
theoretically clean and produces a visually satisfying result.

## Architecture
Single-file `optic.py` (~3000 lines) organized as:

```
[PNG I/O layer]       Raw chunk parser/writer, zlib, CRC-32, filter types
[Image class]         Channel-first float array; geometric & photometric ops
[Filter engine]       2D convolution, separable kernels, edge operators
[Feature detectors]   Harris, FAST
[Morphology engine]   SE-driven binary ops, connected components
[Hough transform]     ρ–θ accumulator, peak finding
[Template matching]   SSD and NCC
[HTML visualizer]     Self-contained pipeline HTML with JS interactivity
[CLI dispatcher]      argparse subcommands, synthetic test-image generator
```

Internal image representation: `Image` holds a flat list of floats in channel-major
order (rows × cols per channel), width, height, and mode (L/RGB/RGBA).

## Feature list

### Required (4)

**R1 — PNG I/O + Core Image Operations**
- From-scratch PNG reader: parse IHDR, concatenate IDAT chunks, zlib-decompress,
  reverse all 5 filter types (None/Sub/Up/Average/Paeth), handle L/RGB/RGBA/LA.
- From-scratch PNG writer: apply Sub filter, zlib-compress, write IHDR+IDAT+IEND
  with CRC-32 (bit-identical to Pillow output on the same data).
- Image ops: grayscale, resize (nearest-neighbor + bilinear), rotate (arbitrary
  angle with bilinear interpolation), flip H/V, crop, pad, brightness/contrast/gamma,
  channel split/merge/blend.

**R2 — Convolution Framework + Canny Edge Detector**
- 2D convolution with arbitrary kernel (separable shortcut for Gaussian).
- Gaussian blur (configurable σ, auto-sized kernel).
- Sobel (X, Y, magnitude, direction) and Prewitt/Scharr variants.
- Full Canny pipeline: Gaussian → gradient magnitude+direction → non-maximum
  suppression (sub-pixel interpolation along gradient) → double-threshold →
  hysteresis BFS to connect strong+weak edge pixels.

**R3 — Harris Corner Detector + FAST Corner Detector**
- Harris: Sobel Ix/Iy → structure tensor M (with Gaussian weighting) →
  response R = det(M) − k·trace(M)² → non-maximum suppression → top-N corners.
- FAST (Features from Accelerated Segment Test): Bresenham circle test (radius 3,
  16 pixels) → contiguous-arc criterion → corner score = max-min difference →
  non-maximum suppression.

**R4 — Morphological Operations + Connected Component Labeling**
- Binary dilation and erosion with arbitrary structuring elements (cross, square,
  disk) — all by direct SE application, no FFT tricks.
- Derived operations: opening, closing, morphological gradient, top-hat,
  black-hat, hit-or-miss.
- Connected component labeling: two-pass algorithm with union-find data structure.
  Returns per-component labels, sizes, bounding boxes, and centroids.

### Stretch (3)

**S1 — Hough Line Transform**
- Standard Hough: binary edge image → (ρ, θ) accumulator with configurable
  resolution → peak finding with NMS → draw detected lines on the image.

**S2 — Template Matching**
- Normalized cross-correlation (NCC) and sum of squared differences (SSD).
- Sliding window over the image, build correlation map, find top-N matches.
- Draw match rectangles on a copy of the image.

**S3 — Interactive HTML Pipeline Visualizer**
- Self-contained single-file HTML (no external deps).
- Show a test image through 6 pipeline stages side by side (original → gray →
  Gaussian blur → Canny edges → Harris corners → Hough lines).
- Hover any stage for details; click to zoom.
- JS slider controls for σ, Canny thresholds, and Harris k parameter.

## Test plan (Phase 5)
1. PNG round-trip: write a synthetic RGBA image, read it back, verify exact equality.
2. Filter type coverage: write one image per filter type, read back.
3. Gaussian: zero-mean after subtracting original, energy doesn't increase.
4. Sobel: gradient of a step edge perpendicular to X should have non-zero Ix, zero Iy.
5. Canny: on a white square on black background, all 4 edges detected.
6. Harris: corners on a checkerboard grid at the right grid intersections.
7. FAST: corners at the corners of a square.
8. Morphological: erosion of a full-black image is all-black; dilation of an all-white
   image is all-white. Opening(Closing(img)) — check idempotence.
9. Connected components: two separated white blobs → two labels.
10. Hough: a horizontal line in an edge image → peak at θ=90°.
11. Template match: a template placed in an image exactly → NCC=1.0 at that location.
