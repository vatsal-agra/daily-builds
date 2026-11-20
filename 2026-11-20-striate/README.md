# Striate

From-scratch 1D barcode toolkit in pure Python: **encode** Code 128 / EAN-13 / UPC-A / EAN-8 / Code 39 / ITF
and **decode them out of raster images** (own PNG codec, gradient edge detection, ink-gain-compensated
symbol matching, checksum validation, multi-scanline voting).

## Status
- Phase 1 (plan): done — see `PLAN.md`
- Phase 2 (core build): done — 4 required features working end-to-end
  (Code128 w/ optimal subsets, EAN/UPC, Code39+ITF, raster scanner); `python3 -m unittest discover -s tests`

- Phase 3 (adversarial review): done — 11 findings fixed, see `REVIEW.md`; regression tests in `tests/test_review.py`
- Phase 4 (stretch + polish): done — rotated scan, GS1-128, robustness benchmark, HTML gallery, SVG XML-escaping bug found+fixed
- Phase 5 (verification): done — `./verify.sh` runs every feature end-to-end + 56 tests, green

Full README arrives in Phase 6.
