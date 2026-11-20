# REVIEW — adversarial pass (Phase 3)

Method: wrote hostile scripts (`/tmp/attack.py`, `/tmp/attack2.py`, later folded into `tests/test_review.py`)
to break encoders, PNG codec, scanner and CLI with rotated / inverted / 1-px / clipped / noisy / unevenly-lit /
streaked / tiny / blank / garbage inputs, plus a brute-force optimality check of the Code 128 encoder.

## Findings (all fixed)

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | **High** | First scanner used adjacent-pair sums (gain-invariant) to match symbols. Wrong: EAN L2 `(2,1,2,2)` and `(1,2,1,3)` have *identical* pair sums (they differ by exactly the ink-gain direction), so EAN-13/EAN-8 silently failed on clean images. | Replaced with explicit ink-gain estimation (`fit_gain` on the Code128 start symbol, start-guard formula for EAN) carried along the symbol with running refinement; `match_char` now compares gain-corrected widths. |
| 2 | **High** | Threshold-based binarization merged blurred narrow spaces (their peak never reached the mid-level): Code39 21/30, ITF 18/30, EAN-13 poor at blur σ=0.9. | Rewrote edge detection as gradient-extremum detection (amplitude independent, sub-pixel centroid). Same fuzz now 30/30 on every symbology. |
| 3 | High | Code128 stop-symbol test used a loose threshold and fired mid-symbol (`PJJ123C` returned nothing). | Stop accepted only if its error ≤1.6 **and** better than the best data-symbol match. |
| 4 | High | **False positive:** a single scanline of random noise decoded to a valid EAN-13 (1 vote). | Every symbology now needs ≥2 agreeing scanlines (unless the image has <4 lines); tall images get ≥1 line per 8px so a ≥16px barcode always has ≥2. 40 noise images → 0 detections. |
| 5 | Medium | Light-on-dark (inverted) barcodes not found. | Horizontal pass retries on inverted samples; reported via `inverted: true`. |
| 6 | Medium | 1-px-module barcodes not found (central difference is blind to a 1-px pulse; smoothing erases it). | Third horizontal mode: no smoothing + forward differences. |
| 7 | Medium | Barcode touching the image border (no quiet zone) not found: the first bar's leading edge never occurs. | Lines are padded with the local background level (first version padded a fixed 255 and *created* an edge on unevenly lit images — found by the illumination test and fixed to use local max). |
| 8 | Medium | Performance: 1000×800 noise took 14 s (every offset ran full pattern matching, ×35 rotation angles). | Cheap quiet-zone/guard-ratio prefilters before matching; rotated passes use ≤36 lines. Same image 4.0 s; blank 1600×1200 1.1 s. |
| 9 | Low | UPC-A hits hid that they're also EAN-13 (leading 0). | `ean13` field added to the detection. |
| 10 | Low | `striate encode ... -o x.txt` exited with code 1 (SystemExit string), inconsistent with other errors (2). | Now an `EncodeError` → exit 2. |
| 11 | Low | Illumination gradient (0.6/0.85 falloff) and washed-out contrast (60 grey levels) untested. | Verified after fix #7; regression tests added. |

## Verified OK (attacked, held up)
- Code 128 encoder is **optimal**: 2000 random strings (controls, lowercase, digits, FNC1) match a Dijkstra brute-force minimum symbol count.
- Rotation 3°…90°, 180°, −20° (clean) and 12°/−27°/63° with blur+noise all decode (≤0.3 s).
- Integrity: 240 barcodes corrupted with 1-3 vertical streaks (black/white, 1-5 px) → **0 wrong decodes** (21-25/40 still read, rest correctly report nothing), including Code 39 / ITF which have no check digit.
- PNG decoder: 1/2/4/8/16-bit gray, palette, gray+alpha, RGBA; rejects interlaced, truncated, corrupt, absurd-size files with `PNGError`.
- Garbage/missing files give exit 2 with a message, never a traceback.

## Known limits (documented, not bugs)
- Modules narrower than ~1.5 px with blur are unreadable (information is gone). Barcodes <16 px tall in tall images may get <2 votes; pass `min_votes=1`.
- Code 39 / ITF carry no mandatory check digit: a defect that is *identical on every row* can produce a plausible wrong read. Use mod-43 / mod-10 check characters.
- Inverted polarity is only tried for horizontal scans; Code 128 FNC4 (extended ASCII) is not supported.

## Phase 4/5 addendum
- 12. (Low) SVG `aria-label` embedded raw barcode text → control characters / quotes made invalid XML. Found by the new `test_svg_wellformed_and_escaped`; text is now sanitised once and quotes are escaped.
- Gallery badge said "-20°" for a 27°-rotated image (coarse 5° scan step); relabelled "scan angle".
