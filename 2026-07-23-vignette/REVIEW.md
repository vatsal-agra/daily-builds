# Adversarial review

Hostile pass over Vignette hunting for bugs, broken edges, and lazy
shortcuts, after Phase 2's core build. Each finding below was reproduced,
then fixed; "fixed" items are checked off with the commit that landed the
fix (this same phase).

## Found and fixed

1. **[CRITICAL, found before this phase's write-up — already fixed during
   Phase 2] Quantization table zigzag/natural-order mismatch.** The
   quantization table constants (`STD_LUMINANCE_QT` etc.) are stored in
   natural row-major order, but `_quantize_zigzag` divided by
   `qtable[i]` (the zigzag scan index) instead of `qtable[n]` (the natural
   index), `_marker_dqt` wrote the table into the file without reordering
   to zigzag (which the format requires), and the decoder's
   `_dequant_idct` had the matching natural/zigzag mixup. All three
   canceled out invisibly at quality 100 (every quant entry scales to 1,
   so which index you use doesn't matter) but caused a PSNR cliff from
   ~40dB to ~13dB at quality 95 and any quality where table entries
   actually differ. Caught by testing a quality *sweep* instead of just
   one setting — the bug was invisible at the one quality (100) an
   initial happy-path test used. Fixed by consistently indexing the
   natural-order in-memory table by the natural position everywhere, and
   only reordering to zigzag at the file-write boundary.

2. **[UI bug] HTML report zoom panel showed the page's checkerboard
   background bleeding through the "low quality" crop image.** Root
   cause: the figcaption text ("quality 5 (6× zoom) — note 8×8 blocking")
   is longer than the caption under the "original" crop, and with no
   explicit width on `.zoom-row figure`, the long caption's shrink-to-fit
   layout pushed the whole figure (and its sibling `.imgwrap` div, whose
   own tiled-transparency CSS background was showing through the gap)
   wider than the 192px image inside it — purely a CSS layout bug, not a
   codec or pixel-data bug (confirmed by directly screenshotting the
   generated PNG bytes outside the page, which rendered as a full opaque
   192×192 square with no gap). Fixed by giving `.zoom-row figure` and
   `.imgwrap` an explicit 192px width so long captions wrap instead of
   expanding the layout.

## Investigated, not bugs (documented so they aren't re-litigated)

3. Tiny synthetic images (down to 1×1) with `(x*7) % 256`-style
   high-frequency test content showed low PSNR (~17–19 dB) at quality 70.
   Verified this is inherent, not a bug: a flat-color image at the same
   tiny sizes gets a normal, size-independent 43.9 dB at the same quality.
   A handful of pixels of near-random noise is fundamentally hard for a
   frequency transform to represent well — same as real JPEG.
4. Pure-black (0,0,0) 32×32 image round-trips at infinite PSNR (bit-exact)
   while pure-white (255,255,255) round-trips at "only" 48.1 dB. Traced to
   the asymmetric level-shift range (block samples shifted into [-128,127],
   not symmetric around 0) landing white's DCT/quantization arithmetic on
   a rounding boundary black doesn't hit. This is expected lossy-codec
   behavior (JPEG is not guaranteed bit-exact for any input), not a defect.
5. `build_optimal_table` with a pathological Fibonacci-weighted frequency
   distribution (the classic adversarial input for unbounded Huffman tree
   depth) correctly detects a >16-bit code length and returns `None`,
   which the encoder already treats as "fall back to the standard table
   for this class" — exercised directly to confirm the fallback path is
   live code, not dead code.
6. Malformed/truncated JPEG bytes (empty input, plain text, truncated
   right after SOI, truncated mid-marker, truncated mid-entropy-data) all
   raise a clear Python exception (`JpegSyntaxError`, `ValueError`, or
   `EOFError`) instead of hanging, silently returning garbage pixels, or
   crashing with an obscure index error.

7. **[fixed] CLI UX**: `vignette analyze/compare/encode` on a missing
   input file dumped a raw Python traceback (`FileNotFoundError`) instead
   of a clean message with a non-zero exit; same for `vignette compare` on
   mismatched image dimensions, or a corrupt/truncated JPEG passed to
   `decode`. Fixed by wrapping `main()`'s dispatch in a handler for
   `FileNotFoundError`, `ValueError`, `decoder.JpegSyntaxError`, and
   `EOFError` that prints `error: <message>` to stderr and exits 1.
   Verified: `vignette analyze doesnotexist.ppm` now prints
   `error: file not found: doesnotexist.ppm` (exit 1) instead of a
   traceback, and `vignette compare` on mismatched dimensions prints
   `error: images must have matching dimensions` (exit 1).
