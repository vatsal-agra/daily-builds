# Adversarial review (Phase 3)

Method: I attacked the Phase-2 build as a hostile reviewer would — (1) a randomized accuracy
harness (`qz bench`, 13 degradation scenarios, deterministic seeds) that grades the scanner against
ground truth, (2) probe tests for edge cases (`*/probe_test.go`), (3) a differential test against the
independent `segno` library, (4) manual CLI abuse, (5) reading the code for unstated assumptions.
Every finding below was reproduced first, then fixed, and has a regression test or bench scenario.

## Findings

| # | Sev | Finding | Reproduction | Fix |
|---|-----|---------|--------------|-----|
| 1 | **High** | Scanner failed 20–25 % of noisy, v11–v15 images: impulse noise inside a finder broke the strict 1:1:3:1:1 run test and required *both* diagonal cross-checks to pass. | bench `noise σ=25 + salt&pepper` 84 % | Added a 3×3 median "denoise" strategy tier (19-exchange sorting network, verified against a naive median), relaxed diagonal check to "at least one". Now 100 %. |
| 2 | **High** | Strongly tilted (≥ 35°) symbols failed: only 20 % success. Three separate causes: (a) three finder *centres* cannot pin down perspective, so version-1 symbols (no alignment pattern) mis-sampled the far corner; (b) finder detection rejected the squashed finder because horizontal/vertical run totals differ 3×; (c) the "squarest angle = top-left" heuristic picks the wrong corner under affine skew. | bench `strong tilt 50°` 20 % | (a) extract the 12 outer ring corners of the three finders (affine-dual-basis extremes) and fit a least-squares homography to 15 points; (b) loosen the h/v consistency to 0.8; (c) offer every plausible vertex as top-left and let format/RS arbitrate. Now 100 %. |
| 3 | **High** | Symbol size was estimated from pixel distances / module size; under tilt this was off by > 2 versions so the right version was never tried (v15 symbols read as v12). | bench `tilt up to 35°` seed 200012 | Stopped trusting geometry: all 40 versions are scored against the **timing pattern** (cheap, ≈150 samples each) and tried best-first. |
| 4 | **High** | Performance DoS: a 3000×2000 white image took 11 s, a noise image **63 s**. Per-pixel 25-point range test in the adaptive threshold, generic `At()` pixel access, and ~45 false finder triples × 5 versions × alignment search at ~150 ms each. | `TestProbeLargeBlankIsFast` | Integral-image variance guard, concrete-type fast paths in `FromImage`, timing-pattern pre-filter before alignment search, finder candidates inside a decoded symbol are retired. 11 s → 1.3 s, 63 s → 5.9 s; 27 s clean-image test → 0.1 s. |
| 5 | **Med** | Zero-value `qr.Options{}` silently **forced mask 0** (the field was `-1 = auto`), so a caller who did not set `Mask` got a worse symbol than `DefaultOptions()`. | `TestProbeZeroValueOptionsAreSane` | `Mask` is now `0 = auto`, `ForceMask(n)` forces mask *n*. |
| 6 | **Med** | `DecodeWith` with an erasure map of the wrong size **panicked** (index out of range during the transpose retry). | `TestProbeErasedMaskWrongSize` | Validated up front, returns an error. |
| 7 | **Med** | `decode -text` could not read art made with `encode -invert` (and the invert option painted the quiet zone the wrong colour, so the art was not a faithful inverse). | manual | `Text(invert)` now inverts the quiet zone too; `ParseText` detects inverted polarity from the top-left cell, tolerates CRLF and trailing blanks. |
| 8 | **Med** | Benchmark scenario "background clutter" drew random lines **through the symbol's own light modules**, measuring a self-inflicted wound, not the scanner (12 % pass). | bench | `sim.Clutter` takes an exclusion rectangle; `Warp` returns the symbol's bounding box. |
| 9 | **Low** | Binary payloads were printed through a UTF-8/Latin-1 text conversion; `decode` had no byte-exact path. | manual | `decode -raw` writes payload bytes verbatim. |
| 10 | **Low** | Error messages stuttered (`qz: qr: bad version range 99..99`) and were unhelpful. | CLI abuse | Prefixes removed; version-range message states the legal range; ECC level validated in `Encode`. |
| 11 | **Low** | Differential test vs `segno` compared only symbols whose bit stream was not nibble-aligned; the others were silently skipped. | reading the test | Investigation showed **segno** (not Quietzone) deviates from ISO 18004 §7.4.9 there (inserts an extra `00` pad byte when the stream ends on a half byte). Those cases are now verified by decoding segno's symbol with our decoder, and the count is logged. |
| 12 | **Low** | Source not `gofmt`-clean. | `gofmt -l` | formatted; verify script fails on drift. |

## Things I attacked that held up
* RS decoder at the exact theoretical limit (`2e + f = ecc`, 3 000 random trials across 7 ECC sizes), beyond the limit (2 000 trials: 100 % rejected or valid codeword, failed decodes never mutate the block).
* 3 000 random corruptions of a valid symbol: no panic, no mis-decode to different text.
* Empty payload, 256-byte all-values payload, max-capacity payloads at every boundary (7089 digits / 4296 alnum / 2953 bytes at v40-L, +1 rejected).
* Inverted colours, no quiet zone, two codes in one image, transparent PNG, sub-images with non-zero origin, 2-px modules, cropped symbols (fail cleanly), images smaller than a symbol.
* Both format-info copies destroyed → brute-force over the 32 (level, mask) pairs recovers the symbol.

## Known limits (accepted, documented in README)
* Kanji / Hanzi mode decoding and Micro QR are not implemented (decoder reports an explicit error).
* Pure-noise 6-megapixel images take ≈ 6 s to reject (all 14 binarisation strategies run).
* Curved surfaces (bottles, cans) are out of scope: the grid model is projective, not a warp field.

## Gate: fresh run-through
`go test ./...`, `qz bench -n 40` (13/13 scenarios 100 %), and every probe above pass with none of the listed issues reproducing.
