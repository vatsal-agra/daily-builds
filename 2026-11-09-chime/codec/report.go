package codec

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"html"
	"image"
	"image/color"
	"image/png"
	"math"
	"strings"
)

// Spectrogram returns dB power (1024-point Hann FFT, hop 512) per frame × 512 bins.
func Spectrogram(x []float64) [][]float64 {
	const n, hop = 1024, 512
	plan := newFFT(n)
	win := make([]float64, n)
	var w2 float64
	for i := range win {
		win[i] = 0.5 - 0.5*math.Cos(2*math.Pi*(float64(i)+0.5)/n)
		w2 += win[i] * win[i]
	}
	buf := make([]complex128, n)
	var out [][]float64
	for s := 0; s < len(x); s += hop {
		for i := 0; i < n; i++ {
			v := 0.0
			if s+i < len(x) {
				v = x[s+i]
			}
			buf[i] = complex(v*win[i], 0)
		}
		plan.transform(buf)
		row := make([]float64, n/2)
		for k := range row {
			re, im := real(buf[k]), imag(buf[k])
			row[k] = 10 * math.Log10((re*re+im*im)/w2+1e-3)
		}
		out = append(out, row)
	}
	return out
}

var heat = []color.RGBA{{4, 3, 20, 255}, {40, 11, 84, 255}, {101, 21, 110, 255}, {159, 42, 99, 255},
	{212, 72, 66, 255}, {245, 125, 21, 255}, {250, 193, 39, 255}, {252, 255, 164, 255}}

func heatColor(v float64) color.RGBA {
	if v < 0 {
		v = 0
	}
	if v > 1 {
		v = 1
	}
	p := v * float64(len(heat)-1)
	i := int(p)
	if i >= len(heat)-1 {
		return heat[len(heat)-1]
	}
	f := p - float64(i)
	a, b := heat[i], heat[i+1]
	l := func(x, y uint8) uint8 { return uint8(float64(x)*(1-f) + float64(y)*f) }
	return color.RGBA{l(a.R, b.R), l(a.G, b.G), l(a.B, b.B), 255}
}

// spectrogramPNG renders dB data to a base64 PNG data URI (≤ maxW columns, 256 rows, low frequency at the bottom).
func spectrogramPNG(sg [][]float64, lo, hi float64, maxW int) string {
	cols := len(sg)
	if cols == 0 {
		return ""
	}
	w := cols
	if w > maxW {
		w = maxW
	}
	img := image.NewRGBA(image.Rect(0, 0, w, 256))
	for x := 0; x < w; x++ {
		c0, c1 := x*cols/w, (x+1)*cols/w
		if c1 <= c0 {
			c1 = c0 + 1
		}
		for y := 0; y < 256; y++ {
			var mx float64 = -1e9
			for c := c0; c < c1 && c < cols; c++ {
				for k := 2 * y; k < 2*y+2; k++ {
					if sg[c][k] > mx {
						mx = sg[c][k]
					}
				}
			}
			img.SetRGBA(x, 255-y, heatColor((mx-lo)/(hi-lo)))
		}
	}
	var b bytes.Buffer
	_ = png.Encode(&b, img)
	return "data:image/png;base64," + base64.StdEncoding.EncodeToString(b.Bytes())
}

func monoMix(a *Audio) []float64 {
	if len(a.Ch) == 1 {
		return a.Ch[0]
	}
	m := make([]float64, a.Frames())
	for i := range m {
		m[i] = (a.Ch[0][i] + a.Ch[1][i]) / 2
	}
	return m
}

func errorSignal(a, d *Audio) []float64 {
	o, q := monoMix(a), monoMix(d)
	e := make([]float64, len(o))
	for i := range e {
		e[i] = q[i] - o[i]
	}
	return e
}

// Report renders a self-contained HTML comparison of the perceptual codec and the flat baseline.
func Report(name string, a *Audio, per, flat *Result) string {
	dur := float64(a.Frames()) / float64(a.Rate)
	const lo, hi = 0.0, 95.0
	orig := spectrogramPNG(Spectrogram(monoMix(a)), lo, hi, 1100)
	dec := spectrogramPNG(Spectrogram(monoMix(per.Dec)), lo, hi, 1100)
	errP := spectrogramPNG(Spectrogram(errorSignal(a, per.Dec)), lo, hi, 1100)
	errF := spectrogramPNG(Spectrogram(errorSignal(a, flat.Dec)), lo, hi, 1100)

	var sb strings.Builder
	w := func(f string, args ...any) { fmt.Fprintf(&sb, f, args...) }
	w(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chime report — %s</title><style>%s</style></head><body><main>`, html.EscapeString(name), reportCSS)
	w(`<header><h1>Chime <span>perceptual audio codec</span></h1><p class="sub">%s · %d ch · %d Hz · %.1f s · target %.0f kbps</p></header>`,
		html.EscapeString(name), len(a.Ch), a.Rate, dur, per.Stats.Kbps)

	w(`<section class="cards">`)
	card := func(title, val, note string) {
		w(`<div class="card"><div class="k">%s</div><div class="v">%s</div><div class="n">%s</div></div>`, title, val, note)
	}
	card("Noise over mask", fmt.Sprintf("%.2f dB", per.M.MeanExcess), fmt.Sprintf("flat baseline %.2f dB", flat.M.MeanExcess))
	card("95th-pct NMR", fmt.Sprintf("%+.1f dB", per.M.P95NMR), fmt.Sprintf("flat %+.1f dB", flat.M.P95NMR))
	card("Pre-echo view (256 pt)", fmt.Sprintf("%.2f dB", per.M.TempExcess), fmt.Sprintf("flat %.2f dB", flat.M.TempExcess))
	card("SNR", fmt.Sprintf("%.1f dB", per.M.SNR), fmt.Sprintf("flat %.1f dB — it wins here, and loses the ear test", flat.M.SNR))
	w(`</section>`)

	w(`<section><h2>Metrics at equal bitrate</h2><div class="tablewrap"><table class="wide"><thead><tr><th></th><th>kbps</th><th>SNR dB</th><th>segSNR dB</th><th>bands over mask</th><th>mean excess dB</th><th>p95 NMR dB</th><th>temporal excess dB</th><th>spectral holes</th></tr></thead><tbody>`)
	for _, r := range []*Result{per, flat} {
		cls := ""
		if r == per {
			cls = ` class="best"`
		}
		w(`<tr%s><th>%s</th><td>%.1f</td><td>%.1f</td><td>%.1f</td><td>%.1f%%</td><td>%.2f</td><td>%+.1f</td><td>%.2f</td><td>%.1f%%</td></tr>`,
			cls, r.Name, r.Stats.Kbps, r.M.SNR, r.M.SegSNR, 100*r.M.AudibleFrac, r.M.MeanExcess, r.M.P95NMR, r.M.TempExcess, 100*r.M.HoleFrac)
	}
	w(`</tbody></table></div><p class="note">“Noise over mask” = how far (in dB, averaged over audible band-frames) coding noise rises above the masking threshold of the original. Chime deliberately gives up SNR to put its noise where the ear cannot hear it. “Spectral holes” are band-frames that lost more than 6 dB of energy: Chime zeroes bands the mask allows, so it has more of them unless noise filling (<code>-nf</code>) is on.</p></section>`)

	w(`<section><h2>Spectrograms</h2><p class="note">Same colour scale (0–95 dB). Frequency runs bottom (0 Hz) to top (%.1f kHz); time left to right.</p><div class="grid">`, float64(a.Rate)/2000)
	fig := func(title, cap, src string) {
		w(`<figure><figcaption><b>%s</b> <span>%s</span></figcaption><img alt="%s" src="%s"></figure>`, title, cap, title, src)
	}
	fig("Original", "what went in", orig)
	fig("Chime decoded", fmt.Sprintf("%.1f kbps", per.Stats.Kbps), dec)
	fig("Chime error", "noise hides under the signal — it follows the spectrum", errP)
	fig("Flat-baseline error", fmt.Sprintf("%.1f kbps — same noise level everywhere", flat.Stats.Kbps), errF)
	w(`</div></section>`)

	// frame strips
	st := per.Stats
	w(`<section><h2>Per-frame decisions</h2>`)
	strip := func(label string, flags []bool, cls string) {
		w(`<div class="strip"><span class="lab">%s</span><svg viewBox="0 0 %d 14" preserveAspectRatio="none" role="img" aria-label="%s">`, label, len(flags), label)
		for i, f := range flags {
			if f {
				w(`<rect x="%d" y="0" width="1" height="14" class="%s"/>`, i, cls)
			}
		}
		w(`</svg></div>`)
	}
	strip(fmt.Sprintf("Short blocks (%d of %d frames)", st.ShortFrames, st.Frames), st.ShortMap, "s1")
	if len(a.Ch) == 2 {
		strip(fmt.Sprintf("M/S stereo (%d of %d frames)", st.MSFrames, st.Frames), st.MSMap, "s2")
	}
	w(`</section>`)

	// bit allocation per band
	lay := LayoutFor(LongM, a.Rate)
	bits := st.BandBits[0]
	nb := float64(st.BlockCnt[0])
	if nb > 0 {
		mx := 0.0
		for _, v := range bits {
			mx = math.Max(mx, v/nb)
		}
		w(`<section><h2>Where the bits go (long blocks)</h2><p class="note">Average bits per block per band (scalefactor + flags + coefficients), by band centre frequency.</p><svg class="bars" viewBox="0 0 %d 150" role="img" aria-label="bits per band">`, lay.NB()*10+30)
		for b, v := range bits {
			h := 0.0
			if mx > 0 {
				h = 120 * v / nb / mx
			}
			w(`<rect x="%d" y="%.1f" width="8" height="%.1f" rx="1.5"><title>%.0f Hz: %.1f bits/block</title></rect>`, 28+b*10, 128-h, h, lay.Hz[b], v/nb)
			if b%6 == 0 {
				w(`<text x="%d" y="144" class="tick">%.1fk</text>`, 28+b*10, lay.Hz[b]/1000)
			}
		}
		w(`<text x="0" y="12" class="tick">%.0f</text><text x="0" y="128" class="tick">0</text></svg></section>`, mx)
	}
	w(`<section><h2>Bitstream budget</h2><div class="tablewrap"><table><tbody>`)
	total := float64(len(per.File)) * 8
	for _, r := range []struct {
		n string
		b float64
	}{{"coefficients", st.CoefBits}, {"scalefactors", st.SFBits}, {"band flags", st.FlagBits}, {"noise filling", st.NoiseBits}} {
		w(`<tr><th>%s</th><td>%.0f bits</td><td>%.1f%%</td></tr>`, r.n, r.b, 100*r.b/total)
	}
	w(`</tbody></table></div></section><footer>Generated by chime · range-coded %d-byte .chm · offset %+.2f dB over the masking threshold</footer></main></body></html>`, len(per.File), st.Offset)
	return sb.String()
}

const reportCSS = `
:root{--bg:#f6f5f2;--fg:#1d1c1a;--mut:#6b675f;--card:#fff;--line:#e2dfd8;--acc:#b4361a;--acc2:#1f6f8b;--best:#fbeee9}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#121110;--fg:#ece9e2;--mut:#9a958a;--card:#1b1a18;--line:#2f2d29;--acc:#f07a57;--acc2:#5cb8d6;--best:#2a1a15}}
:root[data-theme=dark]{--bg:#121110;--fg:#ece9e2;--mut:#9a958a;--card:#1b1a18;--line:#2f2d29;--acc:#f07a57;--acc2:#5cb8d6;--best:#2a1a15}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 16px 48px}
h1{font-size:30px;margin:0;letter-spacing:-.02em}h1 span{font-weight:400;color:var(--mut);font-size:18px;margin-left:8px}
h2{font-size:18px;margin:34px 0 10px}.sub,.note{color:var(--mut);margin:6px 0 12px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin-top:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .k{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}.card .v{font-size:28px;font-weight:650;color:var(--acc);margin:2px 0}.card .n{font-size:13px;color:var(--mut)}
.tablewrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%}table.wide{min-width:640px}th,td{padding:9px 12px;text-align:right;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
th:first-child,thead th{text-align:left;font-weight:600}thead th{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}tr:last-child td,tr:last-child th{border-bottom:0}
tr.best{background:var(--best)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:14px}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
figcaption{padding:8px 12px;font-size:14px}figcaption span{color:var(--mut);margin-left:6px;font-size:13px}
img{display:block;width:100%;height:auto;aspect-ratio:3/1;object-fit:fill;background:#04031a}
.strip{display:flex;align-items:center;gap:12px;margin:8px 0}.strip .lab{flex:0 0 230px;font-size:13px;color:var(--mut)}
.strip svg{flex:1;height:22px;background:var(--card);border:1px solid var(--line);border-radius:6px}.s1{fill:var(--acc)}.s2{fill:var(--acc2)}
@media(max-width:620px){.strip{flex-direction:column;align-items:stretch;gap:4px}.strip .lab{flex:none}}
.bars{width:100%;height:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px}.bars rect{fill:var(--acc2)}.bars rect:hover{fill:var(--acc)}.tick{font-size:9px;fill:var(--mut)}
footer{margin-top:40px;color:var(--mut);font-size:13px}
`
