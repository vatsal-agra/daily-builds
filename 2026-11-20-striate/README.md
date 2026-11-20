# Striate

From-scratch 1D barcode toolkit in pure Python: **encode** Code 128 / EAN-13 / UPC-A / EAN-8 / Code 39 / ITF
and **decode them out of raster images** (own PNG codec, gradient edge detection, ink-gain-compensated
symbol matching, checksum validation, multi-scanline voting).

## Status
- Phase 1 (plan): done — see `PLAN.md`
- Phase 2 (core build): done — 4 required features working end-to-end
  (Code128 w/ optimal subsets, EAN/UPC, Code39+ITF, raster scanner); `python3 -m unittest discover -s tests`

Full README arrives in Phase 6.
