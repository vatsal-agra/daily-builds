# Glyph — Plan

## Concept
A from-scratch **TrueType font engine in Go**: parse a `.ttf` file's binary tables, turn
characters into outlines, rasterize them with exact-area anti-aliasing, lay text out with
kerning/wrapping, and write PNG/SVG — with **no font, image, or graphics libraries**
(stdlib only; `compress/zlib` is used purely as DEFLATE).

## Why it's interesting
Every pixel of text you've ever read went through this pipeline, and nothing in this repo
touches it (no font/typography entry exists; Galley typeset paragraphs but with a toy
glyph source). It is a pile of delightfully fiddly binary formats (big-endian tables,
flag-compressed coordinate deltas, composite glyphs with transforms, four cmap formats,
kern/GPOS pair adjustment) feeding a classic graphics problem (quadratic Béziers →
non-zero-winding area coverage). It is also *verifiable without an oracle*: rasterized
coverage must integrate to the polygon's shoelace area, so correctness is a property test.

## Architecture
```
.ttf bytes ──► ttf.Parse ──► Font{head,maxp,hhea,hmtx,loca,glyf,cmap,kern,GPOS,name,post}
                                 │ Glyph(id) → Outline (contours of on/off-curve points)
                                 ▼
layout.Layout(text, size, width, align) ──► []PlacedGlyph (cmap + advances + kerning + wrap)
                                 ▼
raster.Flatten(outline, scale)  ──► polylines (adaptive quadratic subdivision)
raster.Fill(polylines)          ──► coverage []float (32 sub-scanlines × exact horizontal area, true non-zero)
                                 ▼
img: Gray/RGB canvas ► PNG encoder (own chunk writer, CRC32, filters)   |  SVG path export
ttf.Build / Subset ► writes a valid TTF back out (round-trip oracle)
cmd/glyph: info | render | text | specimen | sdf | svg | subset
```
Packages: `ttf/` (parse+build), `raster/` (flatten, fill, SDF, LCD), `layout/`, `img/`, `cmd/glyph/`.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **TTF parser**: table directory + checksums, head/maxp/hhea/hmtx/loca (short+long), `glyf` simple glyphs (flag run-lengths, short/same deltas) **and composite glyphs** (offsets, scale/2x2, point-matching rejected cleanly), `cmap` formats 0/4/6/12, `name`, defensive bounds checks on malformed input | **required** |
| 2 | **Anti-aliased rasterizer**: adaptive Bézier flattening, true non-zero winding, exact horizontal area coverage × 32 sub-scanlines, fractional glyph positioning | **required** |
| 3 | **Text layout**: cmap lookup, hmtx advances, `kern` format-0 + GPOS pair adjustment (PairPos fmt 1 & 2 with ClassDef/Coverage), line wrapping, left/center/right/justify, line height from hhea, `.notdef` fallback, `\n`/tabs | **required** |
| 4 | **Output pipeline + CLI**: from-scratch PNG encoder (gray/RGB, adaptive filters, CRC), SVG path export, `info`/`render`/`text`/`svg` commands, clear errors for bad files/args | **required** |
| 5 | **Signed distance field** generation + atlas packing, with an SDF→threshold reconstruction check | stretch |
| 6 | **Font writer / subsetter**: re-emit a valid TTF (correct checksums, loca, glyf with recomputed bboxes) containing only the glyphs needed for a string; round-trip verified | stretch |
| 7 | **LCD sub-pixel rendering** (RGB stripes + FIR filter) | stretch |
| 8 | **HTML specimen sheet** (glyph grid + metrics, inline SVG) | stretch |

Target: all 4 required + at least 5 (SDF, subsetter, LCD, specimen, ...) as time permits.

## Verification strategy
- Coverage integral == shoelace area (property test over every glyph of real fonts at several sizes).
- Synthetic fonts built by `ttf.Build` from known outlines → parse → compare (round trip).
- Real OFL fonts (if present on box) parsed: checksums valid, `head.magic`, cmap sanity.
- Golden pixel tests for simple shapes (axis-aligned box = exact fractional coverage).
- Malformed-input fuzz: truncations/bit-flips must error, never panic.
