package render

import (
	"fmt"
	"html"
	"sort"
	"strings"

	"glyph/layout"
	"glyph/raster"
	"glyph/ttf"
)

type block struct {
	name   string
	lo, hi rune
}

var blocks = []block{
	{"Basic Latin", 0x20, 0x7E},
	{"Latin-1 Supplement", 0xA0, 0xFF},
	{"Latin Extended", 0x100, 0x24F},
	{"Punctuation & Symbols", 0x2000, 0x2BFF},
	{"Greek & Cyrillic", 0x370, 0x52F},
}

// inlineText lays text out and returns an <svg> using currentColor, so CSS themes it.
func inlineText(f *ttf.Font, text string, size, width float64, kern bool) string {
	res, err := layout.Layout(f, text, layout.Options{Size: size, Width: width, NoKerning: !kern})
	if err != nil {
		return ""
	}
	scale := size / float64(f.UnitsPerEm)
	w := max(res.Width, width) + 8
	h := res.Height + 8
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg class="txt" viewBox="-4 -4 %s %s" width="%s" height="%s" role="img" aria-label="%s">`, fnum(w), fnum(h), fnum(w), fnum(h), html.EscapeString(text))
	sb.WriteString(`<path fill="currentColor" d="`)
	for _, g := range res.Glyphs {
		o, err := f.Glyph(g.GID)
		if err != nil || len(o.Contours) == 0 {
			continue
		}
		sb.WriteString(PathData(o, raster.Scale(scale, g.X, g.Y, 0)))
	}
	sb.WriteString(`"/></svg>`)
	return sb.String()
}

// Specimen builds a self-contained HTML specimen sheet for the font.
func Specimen(f *ttf.Font, maxGlyphs int) (string, error) {
	if maxGlyphs <= 0 {
		maxGlyphs = 600
	}
	family := f.Name(1)
	if family == "" {
		family = "Untitled font"
	}
	title := family
	if st := f.Name(2); st != "" {
		title += " " + st
	}
	runes := f.Runes()
	if len(runes) == 0 {
		return "", fmt.Errorf("font maps no characters")
	}
	var b strings.Builder
	b.WriteString(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">`)
	fmt.Fprintf(&b, "<title>%s — specimen</title><style>%s</style></head><body>", html.EscapeString(title), specimenCSS)
	fmt.Fprintf(&b, `<header><p class="eyebrow">Type specimen · rendered by Glyph from raw TrueType outlines</p><h1>%s</h1><div class="chips">`, html.EscapeString(title))
	kernSrc := "none"
	if f.HasKerning() {
		kernSrc = "yes"
	}
	p, e, fm := f.CmapInfo()
	chip := func(k, v string) {
		fmt.Fprintf(&b, `<span class="chip"><b>%s</b>%s</span>`, html.EscapeString(k), html.EscapeString(v))
	}
	chip("glyphs", fmt.Sprint(f.NumGlyphs))
	chip("characters", fmt.Sprint(len(runes)))
	chip("units/em", fmt.Sprint(f.UnitsPerEm))
	chip("ascent / descent", fmt.Sprintf("%d / %d", f.Ascent, f.Descent))
	chip("kerning", kernSrc)
	chip("cmap", fmt.Sprintf("%d·%d fmt %d", p, e, fm))
	if bad := f.Verify(); len(bad) == 0 {
		chip("checksums", "valid")
	} else {
		chip("checksums", "invalid")
	}
	b.WriteString(`</div></header><main>`)

	sample := "Sphinx of black quartz, judge my vow."
	fmt.Fprintf(&b, `<section><h2>Sizes</h2><div class="hero">%s</div>`, inlineText(f, sample, 54, 0, true))
	for _, sz := range []float64{30, 20, 14} {
		fmt.Fprintf(&b, `<div class="line"><span class="cap">%d px</span>%s</div>`, int(sz), inlineText(f, "The quick brown fox jumps over the lazy dog 0123456789", sz, 0, true))
	}
	b.WriteString(`</section>`)

	if f.HasKerning() {
		b.WriteString(`<section><h2>Kerning</h2><p class="note">Left: advances only. Right: with the font's kerning applied.</p><div class="kgrid">`)
		for _, w := range []string{"AVATAR", "Toy", "Wave", "LT", "P.A.", "Yo"} {
			l, r := f.Index([]rune(w)[0]), f.Index([]rune(w)[1])
			fmt.Fprintf(&b, `<div class="kcell"><div class="pair">%s<em>%+d</em></div><div class="both"><div><i>plain</i>%s</div><div><i>kerned</i>%s</div></div></div>`,
				html.EscapeString(w), f.Kerning(l, r), inlineText(f, w, 44, 0, false), inlineText(f, w, 44, 0, true))
		}
		b.WriteString(`</div></section>`)
	}

	shown := 0
	for _, bl := range blocks {
		var in []rune
		for _, r := range runes {
			if r >= bl.lo && r <= bl.hi {
				in = append(in, r)
			}
		}
		if len(in) == 0 || shown >= maxGlyphs {
			continue
		}
		sort.Slice(in, func(i, j int) bool { return in[i] < in[j] })
		fmt.Fprintf(&b, `<section><h2>%s <small>%d</small></h2><div class="grid">`, bl.name, len(in))
		for _, r := range in {
			if shown >= maxGlyphs {
				break
			}
			g := f.Index(r)
			o, err := f.Glyph(g)
			if err != nil {
				continue
			}
			adv := f.Advance(g)
			asc, desc := f.Ascent, f.Descent
			top := asc + max(0, f.YMax-asc)/2
			fmt.Fprintf(&b, `<figure title="U+%04X · glyph %d · advance %d"><svg viewBox="-60 %d %d %d">`, r, g, adv, -top, adv+120, top-desc+60)
			fmt.Fprintf(&b, `<line class="g base" x1="-60" x2="%d" y1="0" y2="0"/><line class="g" x1="-60" x2="%d" y1="%d" y2="%d"/><line class="g" x1="-60" x2="%d" y1="%d" y2="%d"/>`, adv+60, adv+60, -asc, -asc, adv+60, -desc, -desc)
			fmt.Fprintf(&b, `<line class="g adv" x1="0" x2="0" y1="%d" y2="%d"/><line class="g adv" x1="%d" x2="%d" y1="%d" y2="%d"/>`, -top, -desc+60, adv, adv, -top, -desc+60)
			fmt.Fprintf(&b, `<path fill="currentColor" d="%s"/></svg><figcaption>%s</figcaption></figure>`, PathData(o, raster.Affine{A: 1, D: -1}), html.EscapeString(codeLabel(r)))
			shown++
		}
		b.WriteString(`</div></section>`)
	}
	if len(runes) > shown {
		fmt.Fprintf(&b, `<p class="note">Showing %d of %d characters (-max to change).</p>`, shown, len(runes))
	}
	b.WriteString(`</main><footer>Generated by Glyph · no font libraries were harmed.</footer></body></html>`)
	return b.String(), nil
}

func codeLabel(r rune) string {
	if r == ' ' {
		return "SP"
	}
	return fmt.Sprintf("%04X", r)
}

const specimenCSS = `
:root{--bg:#f6f3ec;--fg:#1d1b17;--mut:#7a7467;--card:#fffdf8;--line:#dcd5c5;--acc:#b4442b;--guide:#d9a79a}
@media (prefers-color-scheme:dark){:root{--bg:#14161c;--fg:#ece8dd;--mut:#9a9588;--card:#1b1e26;--line:#2c303b;--acc:#ff9b7a;--guide:#5b3b35}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
header{padding:48px 6vw 24px;border-bottom:1px solid var(--line)}
.eyebrow{margin:0 0 8px;color:var(--acc);font-size:12px;letter-spacing:.14em;text-transform:uppercase}
h1{margin:0 0 18px;font:600 clamp(32px,6vw,64px)/1.05 system-ui,sans-serif;letter-spacing:-.02em}
.chips{display:flex;flex-wrap:wrap;gap:8px}.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:4px 12px;font-size:13px;color:var(--mut)}
.chip b{color:var(--fg);font-weight:600;margin-right:6px}
main{padding:8px 6vw 64px}section{margin-top:40px}
h2{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);border-bottom:1px solid var(--line);padding-bottom:8px}
h2 small{color:var(--acc);margin-left:8px}
.hero{padding:12px 0;overflow-x:auto}.line{display:flex;align-items:center;gap:16px;overflow-x:auto;padding:4px 0}
.cap{flex:none;width:48px;font-size:12px;color:var(--mut)}svg.txt{display:block;max-width:100%;height:auto}
.note{color:var(--mut);font-size:13px}
.kgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.kcell{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
.pair{font-size:12px;color:var(--mut);display:flex;justify-content:space-between}.pair em{color:var(--acc);font-style:normal;font-variant-numeric:tabular-nums}
.both{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:end}.both div{min-width:0}.both i{display:block;font:11px ui-monospace,monospace;color:var(--mut);font-style:normal;margin-bottom:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:8px;margin-top:14px}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 6px 4px;text-align:center;transition:transform .12s,border-color .12s}
figure:hover{transform:translateY(-2px);border-color:var(--acc)}
figure svg{width:100%;height:96px;display:block}.g{stroke:var(--guide);stroke-width:5;opacity:.55}.g.base{stroke:var(--acc);opacity:.8}.g.adv{stroke-dasharray:14 14}
figcaption{font:11px ui-monospace,monospace;color:var(--mut)}
footer{padding:24px 6vw;color:var(--mut);font-size:12px;border-top:1px solid var(--line)}
`
