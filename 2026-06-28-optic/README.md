# Optic — Computer Vision from Scratch

A complete, dependency-free computer vision library in pure Python 3.
No NumPy. No Pillow. No OpenCV. Just `math`, `zlib`, `struct`, and `argparse`.

## What it is

Optic implements the classic CV algorithms every textbook covers — raw PNG I/O,
Gaussian blur, Canny edge detection, Harris and FAST corner detectors, binary
morphology, connected component labeling, Hough line transform, template
matching (NCC), bilateral filter, and an interactive HTML pipeline visualizer
— all from scratch, in a single ~2000-line file.

## How to run

```bash
# Demo: runs the full pipeline on synthetic images, writes to demo_out/
python3 optic.py demo

# Edge detection
python3 optic.py edges image.png --sigma 1.4 --low 0.10 --high 0.20

# Corner detection
python3 optic.py corners image.png --method harris --top 50

# Morphological operations
python3 optic.py morph image.png open --se cross --size 3

# Connected components
python3 optic.py components image.png

# Hough line transform
python3 optic.py hough image.png

# Template matching
python3 optic.py match image.png template.png

# Thresholding (Otsu or adaptive)
python3 optic.py thresh image.png --method otsu

# Bilateral denoising
python3 optic.py denoise image.png --sigma-s 3 --sigma-r 0.15

# Image info
python3 optic.py info image.png

# Interactive HTML pipeline visualizer
python3 optic.py viz image.png
# → writes image_pipeline.html (self-contained, no server needed)
```

## Test suite

```bash
python3 test_optic.py -v
# Ran 89 tests in ~1.2s — OK
```

## Features shipped

### Required

**R1 — PNG I/O + Core Image Operations**
- From-scratch PNG reader: IHDR chunk parser, IDAT zlib decompression, all 5
  filter types (None, Sub, Up, Average, Paeth), L/RGB/RGBA/LA color types.
- From-scratch PNG writer: Sub filter, zlib level-6, IHDR+IDAT+IEND with CRC-32.
- Image ops: grayscale, to_rgb, flip H/V, crop, nearest-neighbor and bilinear
  resize, arbitrary-angle rotate (bilinear), normalize, brightness/contrast/gamma,
  channel blend, pad.

**R2 — Convolution + Canny Edge Detector**
- 2D convolution with separable Gaussian shortcut (two 1D passes).
- Gaussian blur (configurable σ, auto-sized kernel).
- Sobel, Prewitt, Scharr gradient operators (Gx, Gy, magnitude, direction).
- Full Canny pipeline: Gaussian → gradient → non-maximum suppression (sub-pixel
  interpolation) → double threshold → BFS hysteresis.

**R3 — Harris + FAST Corner Detectors**
- Harris: Sobel → structure tensor → R = det(M) - k·trace(M)² → NMS → top-N.
- FAST: Bresenham circle (radius 3, 16 pixels) → max-contiguous-arc criterion
  → corner score = max - min on the ring → NMS.

**R4 — Morphology + Connected Components**
- Binary dilation, erosion, opening, closing, morphological gradient, top-hat,
  black-hat, hit-or-miss with arbitrary structuring elements (cross/square/disk).
- Connected component labeling: two-pass union-find with path compression.
  Returns label image, component count, per-component info (size, bbox, centroid),
  and colorized RGB label visualization.
- Otsu's thresholding (between-class variance maximization).
- Adaptive thresholding (local mean via integral image / box blur).

### Stretch

**S1 — Hough Line Transform**
- (ρ, θ) accumulator with configurable resolution, peak finding with NMS,
  draw detected lines on a copy of the image.

**S2 — Template Matching**
- Normalized cross-correlation (NCC) with summed-area tables for O(1) patch
  statistics — sum and sum-of-squares over any rectangle in constant time.
- Sum of squared differences (SSD) variant.
- Top-N match finding with overlap suppression.

**S3 — Interactive HTML Pipeline Visualizer**
- Self-contained single-file HTML (no external deps, no server).
- Dark-themed card layout with 6 pipeline stages side-by-side.
- Click any stage to zoom; ESC to close.
- Base64-embedded PNGs; works fully offline.

**S4 — Bilateral Filter**
- Edge-preserving denoising: spatial Gaussian × range Gaussian weights.
- Precomputed spatial weight table; per-pixel range weight from intensity diff.
- Configurable σ_s (spatial) and σ_r (range) parameters.

## Why this today

Every other daily build in this series has involved audio synthesis, ray
tracing, language parsing, or networking — computer vision is the one major
domain that hasn't been touched. Canny edges are a beautiful pipeline: five
independent ideas (blur, gradient, NMS, threshold, hysteresis) that only work
together. Harris corners emerge from a 2×2 structure tensor and a scalar
determinant. The Hough transform inverts the geometry problem into a voting
problem. Each algorithm is both theoretically satisfying and produces a
visually striking result that you can actually look at.

## Where a human could take this next

- **Real bilinear NCC**: replace the SAT-based NCC with a full integral-image
  solution that runs in O(1) per position regardless of template size.
- **SIFT / ORB descriptors**: add oriented gradient histograms around Harris
  keypoints for rotation-invariant feature matching between two images.
- **Pyramid-based optical flow**: Lucas-Kanade with Gaussian image pyramid for
  tracking keypoints across frames.
- **Watershed segmentation**: gradient-driven flooding from marker seeds for
  object segmentation without binary thresholding.
- **JPEG encoder**: DCT-based compression with quantization tables and Huffman
  coding — the natural next I/O format after PNG.
- **GPU via ctypes**: the inner loops (convolution, morphology, template match)
  are embarrassingly parallel; a ctypes bridge to a tiny C extension would
  give 50-100× speedup on large images.
