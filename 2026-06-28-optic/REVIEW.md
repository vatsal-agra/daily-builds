# Optic — Adversarial Review (Phase 3)

## Methodology
Reviewed every module as a hostile critic: API contracts, boundary conditions,
numerical correctness, error handling, silent-wrong outputs, and UX. Ran targeted
property tests for each algorithm.

---

## Bugs Found & Fixed

### [BUG-1] CRITICAL: Otsu threshold = 0 for binary images → everything classified as foreground
**Location:** `threshold_otsu()` 
**Root cause:** Otsu's algorithm returns `best_t = 0` for a two-value image (e.g. 0.0 and 1.0),
because bin 0 is the optimal split point. The comparison `v >= 0.0` then marks ALL pixels
(including exact-zero background) as foreground → `connected_components` found 1 giant component
instead of 3 distinct shapes.  
**Fix:** Changed threshold to midpoint of the bin: `t_float = (best_t + 0.5) / 255.0`.
Pixels at exactly 0.0 are now correctly classified as background.
**Verified:** `make_shapes(128,128)` now finds 3 components (rectangle, circle, triangle). ✓

### [BUG-2] cmd_viz wrote `foo_pipeline.html.png` instead of `foo_pipeline.html`
**Location:** `cmd_viz()` — `_add_suffix(path, '_pipeline.html')` appended both the suffix
AND the original `.png` extension, then `.replace('.png.html', '.html')` didn't match.  
**Fix:** Changed to `os.path.splitext(args.image)[0] + '_pipeline.html'`.  
**Verified:** `python3 optic.py viz demo_out/shapes.png` now correctly writes `shapes_pipeline.html`. ✓

### [BUG-3] template_match_ncc silently returned empty response when template > image
**Location:** `template_match_ncc()`  
**Root cause:** The loop `for r in range(H - TH + 1)` produces zero iterations when `TH > H`,
leaving an all-zero response map. No error was raised; callers got 0 matches with no explanation.  
**Fix:** Added upfront validation: raises `ValueError("Template (TW×TH) is larger than image (W×H)")`
before any computation.

---

## Issues Documented (not bugs, but notable behaviors)

### [BEHAVIOR-1] Erosion with zero-padding zeroes border pixels
`erode(all_white_image, se)` returns all-white only for interior pixels; the border ring
(where the SE would extend outside the image) is set to 0. This is standard morphological
behavior with zero-padding (same as OpenCV's `BORDER_CONSTANT` with `0`).
A future caller relying on "erosion of a full image = full image" would get a surprise.
Not a bug, documented here.

### [BEHAVIOR-2] FAST NMS: tied scores allow both pixels to survive
If two adjacent pixels (within nms_radius) have identical FAST scores, both appear in
the output. In practice scores are float differences between circle pixels and the test
pixel, so exact ties are extremely rare. No action taken.

### [BEHAVIOR-3] Canny with sigma >> image size produces many "edges"
With `sigma=10` on a 32×32 image, the kernel radius exceeds the image dimensions and
`_clamp_idx` causes heavy border bias. The image gets only slightly blurred (clamp collapse),
and with very low thresholds this produces spurious edges. Expected behavior for an unusual
parameter choice — callers should ensure `3 * sigma << min(W, H)`.

### [BEHAVIOR-4] PNG I/O has ~2/255 float precision loss
Write→Read round-trip loses at most 0.5/255 ≈ 0.002 (standard 8-bit quantization).
Any algorithm using the PNG files as intermediate storage should treat values as
having ±0.5/255 uncertainty.

---

## Coverage review

| Feature | Issue found | Severity | Status |
|---------|------------|----------|--------|
| PNG round-trip (L/RGB/RGBA/LA) | none | — | ✓ |
| Gaussian blur | none | — | ✓ |
| Sobel gradients | none | — | ✓ |
| Canny edges | none | — | ✓ |
| Harris corners | none | — | ✓ |
| FAST corners | NMS ties (BEHAVIOR-2) | minor | documented |
| Morphology | border behavior (BEHAVIOR-1) | minor | documented |
| Connected components | BUG-1 (upstream Otsu) | critical | fixed |
| Hough transform | none | — | ✓ |
| Template match NCC | BUG-3 (silent empty result) | moderate | fixed |
| Otsu threshold | BUG-1 | critical | fixed |
| Adaptive threshold | none | — | ✓ |
| cmd_viz | BUG-2 (bad output path) | moderate | fixed |
| cmd_match, cmd_edges, cmd_corners | none | — | ✓ |
| cmd_morph, cmd_components, cmd_hough | none | — | ✓ |
| HTML visualizer | none | — | ✓ |

---

## Post-fix verification

```
$ python3 optic.py demo --out-dir demo_out
Harris found 40 corners on 128×128 checkerboard     ✓
Canny: 460 edge pixels                              ✓
FAST: 17 corners detected                           ✓
Connected components: 3 found                       ✓  (was 1 before BUG-1 fix)
Hough detected 4 lines                              ✓
Template: 26×26  Matches found: 4  NCC=1.000        ✓
Pipeline HTML → demo_out/pipeline.html              ✓  (was .html.png before BUG-2 fix)
```
