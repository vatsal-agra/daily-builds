# Striate — PLAN

## Concept
A from-scratch **1D barcode toolkit**: encode Code 128 / EAN-13 / UPC-A / EAN-8 / Code 39 / ITF,
render to SVG and PNG, and — the hard half — **decode barcodes out of real raster images**
(own PNG codec, adaptive binarization, run-length analysis, width-ratio classification,
checksum validation, upside-down reads, multi-scanline voting, rotated-image search).
Pure Python 3 stdlib. No PIL, NumPy, zxing, or zbar.

## Why it's interesting
Barcodes look trivial until you try to *read* one: bar widths smear under blur, printers gain/shrink ink,
photos are skewed, and every symbology encodes widths differently (module-width tables for EAN/Code128,
narrow/wide ratios for Code39/ITF). The decoder has to be a tiny signal-processing pipeline with
error detection built into the symbology. Repo has QR but no linear barcodes, no scanner pipeline.

## Architecture
```
striate/
  symbologies/   code128.py ean.py code39.py itf.py   # text <-> module pattern (+ pattern-> text via run widths)
  png.py         # PNG encode/decode (stdlib zlib), PGM
  raster.py      # Image (gray), draw barcode, distortions (blur, noise, skew, rotate, ink-gain)
  scan.py        # binarize -> runs -> per-symbology decode -> vote -> result
  svg.py         # SVG renderer w/ human-readable text
  cli.py         # encode / decode / bench / demo
tests/           # unittest suite
```
Pipeline: gray image → scanline → local-adaptive threshold → run-lengths → trim quiet zones →
try each symbology (both directions) → checksum → collect candidates across many scanlines → majority vote.

## Features
| # | Feature | Status |
|---|---------|--------|
| 1 | Code 128 encoder/decoder: subsets A/B/C, **optimal subset switching** (DP), FNC1, mod-103 checksum | **required** |
| 2 | EAN-13 / UPC-A / EAN-8 encoder + decoder with check digit compute/verify and L/G/R parity-derived first digit | **required** |
| 3 | Code 39 (+ optional mod-43) and ITF (Interleaved 2 of 5) with ratio-based decoding | **required** |
| 4 | Raster scanner: PNG codec, adaptive threshold, multi-scanline voting, upside-down, noise/blur tolerance | **required** |
| 5 | SVG + PNG renderer with human-readable text, configurable module width/height/quiet zone | secondary (ships with 4) |
| 6 | Rotated-image search: try angles, rotate, decode (handles skewed photos) | **stretch** |
| 7 | Robustness benchmark: success-rate vs blur/noise/ink-gain across symbologies | **stretch** |
| 8 | GS1-128 application-identifier parser (AI 01, 10, 17, 21, 310x...) | **stretch** |
| 9 | CLI + self-contained HTML gallery | **stretch** |
