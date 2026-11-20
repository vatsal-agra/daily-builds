# Striate

A from-scratch **1D barcode toolkit in pure Python 3 (stdlib only)**: encode six symbologies, and — the hard half —
**read them back out of noisy raster images**. No PIL, NumPy, zxing or zbar; even the PNG codec is hand-written.

Open `gallery/index.html` for live encodes, damaged-image decodes and robustness charts.

## Run it
```bash
cd 2026-11-20-striate
python3 -m striate encode ean13 400638133393 -o ean.png        # check digit auto-added; .svg works too
python3 -m striate decode ean.png [--json] [--no-rotate]       # PNG or PGM, finds every barcode in the image
python3 -m striate encode gs1 "(01)09501101530003(17)261231(10)LOT42" -o gs1.png
python3 -m striate bench blur noise -n 6                       # success-rate vs degradation
python3 -m striate gallery --bench -o gallery/index.html
./verify.sh                                                     # full demo + all tests (≈30 s)
python3 -m unittest discover -s tests                          # 56 tests
```
Library: `from striate import encode, scan_image, raster` →
`img = raster.render(encode("code128", "HELLO"), module=3); scan_image(img)[0].text`.

## Features
**Encoders** — Code 128 (subsets A/B/C, FNC1, *provably minimal* symbol count via DP incl. SHIFT, verified against a brute-force
search), EAN-13, UPC-A, EAN-8 (GS1 check digits, L/G/R parity), Code 39 (+ optional mod-43), ITF (+ optional mod-10), SVG and PNG output.

**Scanner** (`striate/scan.py`)
- gradient-extremum **sub-pixel edge detection** (survives blur that merges narrow spaces under thresholding)
- **ink-gain estimation** carried through each symbol — needed because adjacent-pair sums can't tell some EAN digits apart
- per-symbology decoders working on run lengths: module-width tables (Code128/EAN) and narrow/wide clustering (Code39/ITF)
- checksum validation, both reading directions, multi-scanline **voting** (≥2 lines agree → no chance decodes in noise)
- finds several barcodes in one image, amid clutter, touching the image border, light-on-dark, 1-px modules,
  uneven lighting, low contrast, and **any rotation** (scan-angle sweep, incl. vertical)
- zero wrong reads in all corruption tests (streaks, noise); detection reports votes, bbox, module size, quality

**Extras** — GS1-128 AI parser/builder (GTIN/SSCC check digits, date validation, decimal weights, FNC1 separators),
robustness benchmark with charts, self-contained HTML gallery, CLI with meaningful exit codes (0 ok, 1 none found, 2 error).

## Layout
`striate/symbologies/` encoders + tables · `scan.py` scanner · `png.py` PNG/PGM codec · `raster.py` rendering & degradations
· `gs1.py` · `bench.py` · `gallery.py` · `cli.py` · `tests/` · `PLAN.md` · `REVIEW.md` (12 findings, all fixed) · `verify.sh`

## Why this today
The repo has QR/graphics/solver projects but nothing that *reads* a physical-world signal. Barcodes look trivial until you scan
one: widths smear, ink spreads, photos rotate. It's a compact signal-processing + error-detection problem with a clear
pass/fail oracle (round-trip), which made the adversarial review genuinely productive — the first matching strategy was
mathematically wrong and the first edge detector was too brittle, both caught by attacking it.

## Known limits
Modules below ~1.5 px under blur are unreadable; barcodes <16 px tall in tall images may get <2 votes (`min_votes=1`);
Code 39/ITF have no mandatory check digit, so a defect identical on every row can yield a plausible wrong read (use check digits);
no FNC4/extended ASCII, no 2D codes, no perspective correction (only rotation).

## Where a human could take this next
- Perspective/affine rectification (find the quad, warp) for phone photos; JPEG input
- Add Codabar, Code 93, MSI, EAN-2/5 supplements, GS1 DataBar; Code 128 FNC4
- Use soft decisions: Reed-Solomon-like repair for Code 128 via checksum + candidate digit swaps
- Real-photo test corpus and a comparison against zbar/zxing success rates
- Port the hot loops to C/NumPy; streaming video scanning with temporal voting
