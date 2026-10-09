# Glyph — TrueType font engine from scratch (Go)

**Status: Phase 2 (core build) complete** — the four required features work end-to-end.
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
