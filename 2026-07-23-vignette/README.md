# Vignette

A from-scratch, pure-Python baseline JPEG-style lossy image codec — the
transform-coding pipeline (DCT, quantization, Huffman entropy coding) that
underlies real-world image and video compression, implemented by hand from
first principles down to real, spec-valid `.jpg` file bytes any image
viewer can open.

**Status: Phase 2 (core build) complete.** See [PLAN.md](./PLAN.md) for the
full architecture and feature list.

## What works right now

- **Real baseline JFIF encoder** (`vignette/encoder.py`) — RGB → YCbCr →
  4:2:0 chroma subsampling → 8×8 DCT → quantization → zigzag → DC DPCM/AC
  RLE → Huffman → a real `.jpg` file, verified as a genuine JPEG by the
  system `file` utility (independent external check).
- **Full decoder** (`vignette/decoder.py`) — parses real marker segments and
  reconstructs pixels via the inverse pipeline.
- **Quality/rate-distortion toolkit** (`vignette/metrics.py`, `cli.py
  analyze`) — PSNR/SSIM/size/bpp across a quality sweep.
- **Interactive HTML report** (`vignette/visualize.py`, `cli.py report`) —
  quality slider, live PSNR/SSIM/size, 6×zoom blocking-artifact panel, and
  a DCT-coefficient heatmap. Generate it with:

  ```
  python3 -m vignette.cli report out/report.html
  ```

## Quick start

```
python3 -m vignette.cli encode gradient out/gradient.jpg -q 75
python3 -m vignette.cli decode out/gradient.jpg out/gradient.png
python3 -m vignette.cli analyze circles --qualities 95 75 50 25 10
python3 -m vignette.cli report out/report.html
```

`encode`/`analyze` accept either a built-in procedural test image name
(`gradient`, `checkerboard`, `circles`, `plasma`, `textbars` — generated
deterministically, no external image files needed) or a path to a binary
PPM (P6) file.

## Remaining work

Adversarial review, stretch features (optimal per-image Huffman tables are
implemented — `encode --optimal-huffman` — and quality-ladder gallery),
polish, and a full automated test suite/demo script land in the phases that
follow; this README will be updated after each.
