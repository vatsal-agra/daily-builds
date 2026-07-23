# Vignette

A from-scratch, pure-Python baseline JPEG-style lossy image codec — the
transform-coding pipeline (DCT, quantization, Huffman entropy coding) that
underlies real-world image and video compression, implemented by hand from
first principles down to real, spec-valid `.jpg` file bytes any image
viewer can open.

**Status: Phase 5 (verification) complete — 50/50 tests passing.** See
[PLAN.md](./PLAN.md) for the full architecture and feature list, and
[REVIEW.md](./REVIEW.md) for the hostile-testing pass (a critical
quantization-table indexing bug, an HTML report layout bug, and a CLI
error-handling gap were found and fixed).

## Stretch features

- **Optimal per-image Huffman tables** (`encode --optimal-huffman`) —
  builds real symbol-frequency-driven canonical Huffman tables instead of
  the fixed standard ones (still a spec-legal custom DHT segment).
  Lossless: reconstructed pixels are bit-identical to the standard-table
  encode at the same quality, just smaller — confirmed ~24% smaller on a
  test image at quality 60.
- **Quality-ladder artifact gallery** (`vignette gallery`) — every test
  image rendered across a quality ladder from 100 down to 1, with size/
  ratio/PSNR annotated per step, visually demonstrating the classic JPEG
  artifact progression (blocking → ringing → chroma bleed).

## Polish

- Image dimensions are validated at construction (`Image(0, h)` etc. now
  raise a clear error instead of failing deep inside the pipeline).
- The CLI catches missing files, malformed PPM/JPEG input, and dimension
  mismatches and prints a one-line `error: ...` message with exit code 1
  instead of a raw traceback.
- Output paths auto-create their parent directory (`encode`, `decode`,
  `report`, `gallery`).

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

## Tests

```
python3 -m unittest discover -s tests -v   # 50 tests
./demo.sh                                  # tests + full CLI walkthrough
```

The suite covers the DCT (against a brute-force O(N^4) reference and a
round-trip identity check), canonical Huffman coding (prefix-free codes,
bit-stuffing, the optimal-table builder including its pathological-input
fallback), the PNG encoder (chunk/CRC structure, decompressed-length math,
a from-scratch unfilter that recovers the original pixels), PSNR/SSIM,
image I/O, and the codec end-to-end: every test image at five qualities,
non-multiple-of-16 dimensions, quality clamping, monotonic PSNR vs.
quality, lossless-relative-to-standard-tables optimal Huffman, malformed/
truncated input handling, and a regression test that pins down the
quantization-table indexing bug found in Phase 3 so it can't come back
unnoticed.

## Remaining work

None outstanding — see Phase 6 for the final feature summary below.
