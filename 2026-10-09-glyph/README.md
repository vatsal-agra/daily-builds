# Glyph — TrueType font engine from scratch (Go)

**Status: Phase 5 (verification) complete** — `./demo.sh` drives every feature and runs ~90 tests (race-clean); `./mutants.py` kills 23/23 injected bugs. 4 required + 4 stretch features shipped; 9 review findings fixed ([REVIEW.md](REVIEW.md)).
See [PLAN.md](PLAN.md). The full README arrives in Phase 6.

## Try it
```bash
go build -o glyph ./cmd/glyph
./glyph info testdata/fonts/Lora-Regular.ttf
./glyph glyph -font testdata/fonts/Lora-Regular.ttf -char g -size 40 -ascii
./glyph text -font testdata/fonts/Lora-Regular.ttf -size 28 -width 420 -align justify -o out.png "The quick brown fox…"
./glyph svg  -font testdata/fonts/Lora-Italic.ttf -size 40 -o out.svg "Hello, Glyph!"
```

## Built so far (required features)
1. **TTF parser** (`ttf/`): table directory + checksums, head/maxp/hhea/hmtx/loca, simple and composite glyphs, cmap 0/4/6/12, name, kern + GPOS pair kerning.
2. **Anti-aliased rasterizer** (`raster/`): adaptive Bézier flattening, true non-zero winding, exact horizontal coverage × 32 sub-scanlines.
3. **Text layout** (`layout/`): advances, kerning, wrapping, left/center/right/justify.
4. **Output + CLI** (`img/`, `render/`, `cmd/glyph/`): own PNG encoder, SVG export, `info`/`text`/`glyph`/`svg`.

## Stretch features (Phase 4)
5. **SDF atlas** — `glyph sdf`: exact signed-distance fields, shelf-packed atlas PNG + JSON metrics (bearings, advances, kerning), and a text renderer that draws at any size from the atlas alone.
6. **Font writer / subsetter** — `glyph subset`: re-emits a valid TTF (cmap 4 + 12, glyf with flag compression, kern, checksums); a 134 KB font shrinks to ~3 KB for a short string.
7. **LCD sub-pixel rendering** — `glyph lcd`: 3× horizontal sampling + FreeType's 5-tap FIR filter.
8. **HTML specimen** — `glyph specimen`: size ladder, kerning on/off pairs, glyph grid with metric guides, light/dark themed.
