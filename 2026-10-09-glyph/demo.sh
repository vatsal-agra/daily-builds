#!/usr/bin/env bash
# End-to-end demo: builds the CLI, then drives every feature on the bundled fonts and
# checks each output. Artifacts land in ./examples (committed as a visual record).
set -euo pipefail
cd "$(dirname "$0")"
F=testdata/fonts
OUT=examples
mkdir -p "$OUT"
go build -o "$OUT/.glyph" ./cmd/glyph
G="$OUT/.glyph"
ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
need() { [ -s "$1" ] || { echo "MISSING OUTPUT $1" >&2; exit 1; }; }

echo "1. TTF parser"
$G info $F/Lora-Regular.ttf | tee "$OUT/info-lora.txt" | grep -q "checksums   OK" && ok "Lora parsed, all table checksums valid"
$G info $F/JetBrainsMono-Regular.ttf | grep -q "kerning     none" && ok "monospace font: no kerning, parsed fine"
$G glyph -font $F/Lora-Regular.ttf -char g -size 36 -ascii | tee "$OUT/glyph-g.txt" | head -1
ok "single glyph rasterized to ASCII art ($(wc -l < "$OUT/glyph-g.txt") rows)"

echo "2/3. Rasterizer + layout (kerning, wrapping, alignment)"
TXT="Typography is the craft of arranging type. AVATAR, Wave, To and Ty tuck together when kerning works; the rest of this sentence only exists to make the paragraph wrap across several lines."
for al in left center right justify; do
  $G text -font $F/Lora-Regular.ttf -size 22 -width 420 -align $al -o "$OUT/text-$al.png" "$TXT" >/dev/null
  need "$OUT/text-$al.png"
done
ok "4 alignments written"
$G text -font $F/Lora-Regular.ttf -size 64 -o "$OUT/kern-on.png" "AVATAR To" >/dev/null
$G text -font $F/Lora-Regular.ttf -size 64 -no-kern -o "$OUT/kern-off.png" "AVATAR To" >/dev/null
[ "$(stat -c %s "$OUT/kern-on.png")" != "$(stat -c %s "$OUT/kern-off.png")" ] && ok "kerning changes the rendering"
$G text -font $F/Lora-Italic.ttf -size 56 -slant 0.15 -fg '#ffd27a' -bg '#1b1f3a' -o "$OUT/colour.png" "Quartz Jinx" >/dev/null
$G text -font $F/InstrumentSans-Regular.ttf -size 13 -width 360 -align center -o "$OUT/small.png" "Small text at thirteen pixels must stay legible: the quick brown fox jumps over the lazy dog 0123456789." >/dev/null
ok "colour, slant and small-size text"

echo "4. PNG + SVG output"
$G svg -font $F/Lora-Italic.ttf -size 48 -o "$OUT/vector.svg" "Hello, Glyph!" >/dev/null
grep -q "<path" "$OUT/vector.svg" && ok "SVG with exact quadratic outlines"

echo "5. SDF atlas"
$G sdf -font $F/Lora-Regular.ttf -px 48 -spread 8 -size 96 -o "$OUT/atlas.png" -demo "$OUT/sdf-text.png" "SDF Quartz" >/dev/null
need "$OUT/atlas.json"; need "$OUT/sdf-text.png"; ok "atlas + JSON + text drawn from the atlas alone"

echo "6. Subsetter"
$G subset -font $F/Lora-Regular.ttf -o "$OUT/lora-subset.ttf" "Hello, Glyph! AVATAR" | tee /dev/stderr >/dev/null
$G info "$OUT/lora-subset.ttf" | grep -q "checksums   OK" && ok "subset is a valid font"
$G text -font "$OUT/lora-subset.ttf" -size 40 -o "$OUT/from-subset.png" "Hello AVATAR" >/dev/null && ok "subset renders text"

echo "7. LCD sub-pixel"
$G lcd -font $F/InstrumentSans-Regular.ttf -size 18 -o "$OUT/lcd.png" "LCD sub-pixel text: Hamburgefonstiv 0123" >/dev/null && ok "LCD written"

echo "8. Specimen"
$G specimen -font $F/Lora-Regular.ttf -max 200 -o "$OUT/specimen.html" >/dev/null && ok "HTML specimen written"

rm -f "$OUT/.glyph"
echo
echo "Running the full test suite…"
go test -count=1 ./... 2>&1 | sed 's/^/  /'
echo "demo OK — see ./examples"
