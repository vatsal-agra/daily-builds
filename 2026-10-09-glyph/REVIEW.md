# Adversarial review (Phase 3)

Method: read the Phase-2 code as a hostile reviewer, then attacked it — random
truncation/bit-flip fuzzing of every bundled font, hand-crafted hostile tables, odd
layout inputs, CLI misuse, and visual inspection of output at 13 px and 64 px.
Each finding below has a regression test (file noted) that failed or would have failed
before the fix.

| # | Severity | Finding | Fix | Regression test |
|---|----------|---------|-----|-----------------|
| R1 | high | `cmap` formats 4/12 were not validated for sorted, non-overlapping ranges. A 1 MB hostile font could list the same 1.1 M-rune range thousands of times, so `Runes()` would burn minutes/gigabytes. Overlapping ranges also made binary-search lookup return arbitrary results. | Subtables are validated at parse time (sorted, disjoint, in-bounds, count fits the data); invalid subtables are skipped, and a font with none left is rejected. | `ttf/review_test.go` `TestCmap12RejectsOverlappingGroups`, `TestCmap4RejectsUnsortedSegments` |
| R2 | high | `raster.Render` allocated a bitmap the size of the glyph's bounds with no limit. Setting `unitsPerEm=16` (or `-size 4000` on a hostile outline) asked for tens of GB. | Bitmap window clamped to `MaxDim`=6000 px per side; clipped ink is simply outside the window. | `render/review_test.go` `TestRenderBitmapBounded` |
| R3 | medium | Wrap width narrower than one glyph produced a canvas narrower than the glyph — ink was clipped at the right edge. | Canvas is now sized from the *actual* ink extents of every rasterized glyph (union with the layout box). | `TestNarrowWrapDoesNotClip` |
| R4 | medium | Synthetic slant clipped: negative slant hung off the left edge; positive slant clipped descenders/accents. | Same ink-extent sizing as R3; SVG export computes its `viewBox` from outline extents too. | `TestSlantNeverClips` |
| R5 | medium | `Font.Glyph` mutated a shared cache map with no lock — a data race for any concurrent user. | `sync.Mutex` around glyph resolution. | `ttf` `TestGlyphConcurrent` (run with `-race`) |
| R6 | medium | `kern` subtables flagged *cross-stream* (vertical kerning) were applied as horizontal advance adjustments. | Cross-stream, vertical and "minimum" subtables are skipped. | `TestKernSkipsCrossStream` |
| R7 | medium | `hmtx` left-side-bearing was ignored. TrueType places the glyph so that `xMin == lsb`; fonts where the two disagree rendered shifted. | `Glyph` translates the outline by `lsb − xMin` (what FreeType does). Invariant `xMin == lsb` asserted over every glyph of every bundled font. | `TestOutlineXMinEqualsLSB`, `TestLSBShiftApplied` |
| R8 | low | `-fg zzz` error echoed the internally expanded `"zzzzzz"` instead of what the user typed. | Report the original string. | manual / CLI test in Phase 5 |
| R9 | low | Ink beside a negative left side bearing (e.g. `W`, italic `f`) touched the canvas edge when `-pad 0`. | Covered by the R3 ink-extent fix. | `TestNarrowWrapDoesNotClip` |

## Examined and found OK (kept, with reasoning)
- Random fuzzing (≈ 600 mutated fonts per run, truncation / bit flips / header smashing): zero panics, zero hangs — all parse errors surface as `ErrMalformed`.
- Composite glyph recursion: depth capped at 6 and a global 256-component budget, so self-referencing or exponential composites terminate with an error.
- Baselines are snapped to whole pixels (`math.Round(g.Y)`): line pitch can jitter by ±0.5 px but horizontal stems stay crisp. A deliberate trade-off, not a bug.
- Flattening tolerance 0.02 px with a 256-segment cap per curve: verified against brute-force point sampling (`raster/area_test.go`).

## Known limitations (documented, not fixed)
- No GSUB (ligatures, contextual alternates), no mark positioning, no bidi/complex scripts: `fi` renders as two glyphs. (A GSUB `liga` pass is a stretch candidate.)
- No hinting: TrueType bytecode is never executed (rendering is unhinted, like modern grayscale-AA rasterizers).
- CFF/OpenType-PostScript (`OTTO`) and `.ttc` collections are rejected with a clear message.
- GPOS script/language selection is ignored: all lookups of the `kern` feature apply.

## Fresh run-through
After the fixes: full `go test -race ./...`, fuzz loop, the CLI misuse matrix (13 bad invocations — each gives a one-line error, exit 1, no panic), and re-rendering the Phase-2 samples — none of R1–R9 reproduces.
