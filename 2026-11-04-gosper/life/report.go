package life

import (
	"encoding/base64"
	"fmt"
	"html"
	"math"
	"strings"
)

// ReportData is everything the HTML report shows.
type ReportData struct {
	Name     string
	Rule     Rule
	Cells    []Point
	Snaps    []uint64 // generations to snapshot
	Period   PeriodResult
	Settle   *Settle
	Growth   []Checkpoint
	GrowthC  GrowthClass
	PopCurve []uint64 // population per generation, from gen 0
	Notes    []string
}

// snapshot renders the pattern at generation g into a base64 PNG.
func snapshot(rule Rule, pts []Point, g uint64, dark bool) (img string, pop uint64, w, h int64, err error) {
	s := NewSim(rule)
	if err = s.SetCells(append([]Point(nil), pts...), true); err != nil {
		return
	}
	if err = s.Step(g); err != nil {
		return
	}
	pop = s.Population()
	if x0, y0, x1, y1, ok := s.BBox(); ok {
		w, h = x1-x0+1, y1-y0+1
	}
	th := DarkTheme
	if !dark {
		th = LightTheme
	}
	im := RenderImage(s, FitView(s, 420, 420), 420, 420, th)
	b, err := EncodePNG(im)
	if err != nil {
		return
	}
	return base64.StdEncoding.EncodeToString(b), pop, w, h, nil
}

func commas(n uint64) string {
	s := fmt.Sprint(n)
	var out []byte
	for i := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			out = append(out, ',')
		}
		out = append(out, s[i])
	}
	return string(out)
}

// lineChart builds an inline SVG line chart. If logLog, both axes are log2.
func lineChart(xs, ys []float64, logLog bool, xlabel, ylabel string) string {
	const W, H, L, R, T, B = 560.0, 260.0, 58.0, 14.0, 12.0, 38.0
	if len(xs) == 0 {
		return "<p class=muted>(no data)</p>"
	}
	tx := func(v float64) float64 { return v }
	ty := func(v float64) float64 { return v }
	if logLog {
		tx = func(v float64) float64 { return math.Log2(math.Max(v, 1)) }
		ty = func(v float64) float64 { return math.Log2(math.Max(v, 1)) }
	}
	minx, maxx, miny, maxy := math.Inf(1), math.Inf(-1), math.Inf(1), math.Inf(-1)
	for i := range xs {
		minx, maxx = math.Min(minx, tx(xs[i])), math.Max(maxx, tx(xs[i]))
		miny, maxy = math.Min(miny, ty(ys[i])), math.Max(maxy, ty(ys[i]))
	}
	if !logLog {
		miny = 0
	}
	if maxx == minx {
		maxx = minx + 1
	}
	if maxy == miny {
		maxy = miny + 1
	}
	px := func(v float64) float64 { return L + (tx(v)-minx)/(maxx-minx)*(W-L-R) }
	py := func(v float64) float64 { return T + (1-(ty(v)-miny)/(maxy-miny))*(H-T-B) }
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg viewBox="0 0 %g %g" role="img" aria-label="%s vs %s">`, W, H, html.EscapeString(ylabel), html.EscapeString(xlabel))
	label := func(v float64, log bool) string {
		if log {
			return "2^" + fmt.Sprint(int(math.Round(v)))
		}
		return commas(uint64(math.Max(v, 0)))
	}
	for i := 0; i <= 4; i++ {
		fy := miny + (maxy-miny)*float64(i)/4
		y := T + (1-float64(i)/4)*(H-T-B)
		fmt.Fprintf(&sb, `<line class=grid x1=%g x2=%g y1=%g y2=%g /><text class=tick x=%g y=%g text-anchor=end>%s</text>`, L, W-R, y, y, L-6, y+4, label(fy, logLog))
		fx := minx + (maxx-minx)*float64(i)/4
		x := L + float64(i)/4*(W-L-R)
		fmt.Fprintf(&sb, `<text class=tick x=%g y=%g text-anchor=middle>%s</text>`, x, H-B+16, label(fx, logLog))
	}
	var pts []string
	for i := range xs {
		pts = append(pts, fmt.Sprintf("%.1f,%.1f", px(xs[i]), py(ys[i])))
	}
	fmt.Fprintf(&sb, `<polyline class=line points="%s" />`, strings.Join(pts, " "))
	if len(xs) <= 80 {
		for i := range xs {
			fmt.Fprintf(&sb, `<circle class=dot cx=%.1f cy=%.1f r=2.6 />`, px(xs[i]), py(ys[i]))
		}
	}
	fmt.Fprintf(&sb, `<text class=axis x=%g y=%g text-anchor=middle>%s</text>`, (L+W-R)/2, H-4, html.EscapeString(xlabel))
	fmt.Fprintf(&sb, `<text class=axis transform="rotate(-90)" x=%g y=14 text-anchor=middle>%s</text>`, -(T + (H-T-B)/2), html.EscapeString(ylabel))
	sb.WriteString("</svg>")
	return sb.String()
}

// HTMLReport renders a self-contained report (inline SVG charts, embedded PNG
// snapshots, light/dark aware, phone friendly).
func HTMLReport(d ReportData) (string, error) {
	var sb strings.Builder
	esc := html.EscapeString
	sb.WriteString(reportHead)
	fmt.Fprintf(&sb, "<title>%s — Gosper report</title></head><body><main>", esc(d.Name))
	fmt.Fprintf(&sb, `<header><p class=eyebrow>Gosper · Hashlife report</p><h1>%s</h1><p class=muted>rule <code>%s</code> · %s starting cells</p></header>`,
		esc(d.Name), d.Rule, commas(uint64(len(d.Cells))))

	// verdict cards
	sb.WriteString(`<section class=cards>`)
	card := func(k, v, sub string) {
		fmt.Fprintf(&sb, `<div class=card><div class=k>%s</div><div class=v>%s</div><div class=sub>%s</div></div>`, esc(k), esc(v), esc(sub))
	}
	switch d.Period.Kind {
	case KindStill:
		card("Behaviour", "Still life", fmt.Sprintf("%d cells · %d×%d", d.Period.Population, d.Period.W, d.Period.H))
	case KindOscillator:
		card("Behaviour", fmt.Sprintf("Oscillator p%d", d.Period.Period), fmt.Sprintf("%d cells in phase 0", d.Period.Population))
	case KindSpaceship:
		card("Behaviour", fmt.Sprintf("Spaceship p%d", d.Period.Period), d.Period.Speed()+fmt.Sprintf(" · (%d,%d) per period", d.Period.Dx, d.Period.Dy))
	case KindDies:
		card("Behaviour", "Dies out", fmt.Sprintf("extinct at generation %d", d.Period.DiesAt))
	case KindEmpty:
		card("Behaviour", "Empty", "")
	default:
		card("Behaviour", "Evolving", "not translation-periodic")
	}
	if st := d.Settle; st != nil {
		switch {
		case st.Died:
			card("Fate", "Extinct", fmt.Sprintf("gen %s · peak %s", commas(st.DiedAt), commas(st.PeakPop)))
		case st.Settled:
			sub := fmt.Sprintf("peak %s at gen %s", commas(st.PeakPop), commas(st.PeakGen))
			if st.HorizonGen > 0 {
				ok := "look-ahead confirmed"
				if !st.HorizonOK {
					ok = "look-ahead FAILED"
				}
				sub += fmt.Sprintf(" · %s to gen %s", ok, commas(st.HorizonGen))
			}
			card("Fate", fmt.Sprintf("Settles at gen %s", commas(st.AtGen)), fmt.Sprintf("population %s · %s", commas(st.FinalPop), sub))
		default:
			card("Fate", "Not settled", fmt.Sprintf("after %s generations", commas(st.Generations)))
		}
	}
	if len(d.Growth) > 0 {
		last := d.Growth[len(d.Growth)-1]
		card("Growth", d.GrowthC.Label, fmt.Sprintf("pop ∼ t^%.2f · %s cells at gen 2^%d", d.GrowthC.Exponent, commas(last.Pop), last.J))
	}
	sb.WriteString(`</section>`)

	// snapshots
	sb.WriteString(`<h2>Snapshots</h2><p class=muted>Rendered straight from the quadtree; zoomed-out views are density shaded.</p><section class=snaps>`)
	for _, g := range d.Snaps {
		dark, _, _, _, err := snapshot(d.Rule, d.Cells, g, true)
		if err != nil {
			fmt.Fprintf(&sb, `<figure><div class=missing>%s</div><figcaption>gen %s</figcaption></figure>`, esc(err.Error()), commas(g))
			continue
		}
		light, pop, w, h, _ := snapshot(d.Rule, d.Cells, g, false)
		fmt.Fprintf(&sb, `<figure><img class=dark src="data:image/png;base64,%s" alt="generation %d"><img class=light src="data:image/png;base64,%s" alt="generation %d"><figcaption><b>gen %s</b><br>%s cells · %s×%s</figcaption></figure>`,
			dark, g, light, g, commas(g), commas(pop), commas(uint64(w)), commas(uint64(h)))
	}
	sb.WriteString(`</section>`)

	if len(d.PopCurve) > 1 {
		var xs, ys []float64
		step := 1
		if len(d.PopCurve) > 1500 {
			step = len(d.PopCurve) / 1500
		}
		for i := 0; i < len(d.PopCurve); i += step {
			xs, ys = append(xs, float64(i)), append(ys, float64(d.PopCurve[i]))
		}
		fmt.Fprintf(&sb, `<h2>Population, generation by generation</h2><div class=chart>%s</div>`, lineChart(xs, ys, false, "generation", "live cells"))
	}
	if len(d.Growth) > 2 {
		var xs, ys []float64
		for _, c := range d.Growth {
			xs, ys = append(xs, float64(c.Gen)), append(ys, float64(c.Pop))
		}
		fmt.Fprintf(&sb, `<h2>Population at generation 2<sup>j</sup> (log–log)</h2><div class=chart>%s</div><p class=muted>A flat line means the pattern settles; slope 1 is linear growth (a gun); slope 2 is quadratic (a breeder). Fitted slope: <b>%.2f</b> → %s.</p>`,
			lineChart(xs, ys, true, "generation", "population"), d.GrowthC.Exponent, esc(d.GrowthC.Label))
		sb.WriteString(`<details><summary>Checkpoint table</summary><table><tr><th>generation</th><th>population</th><th>bounding box</th></tr>`)
		for _, c := range d.Growth {
			fmt.Fprintf(&sb, `<tr><td>2<sup>%d</sup> = %s</td><td>%s</td><td>%s × %s</td></tr>`, c.J, commas(c.Gen), commas(c.Pop), commas(c.W), commas(c.H))
		}
		sb.WriteString(`</table></details>`)
	}
	for _, n := range d.Notes {
		fmt.Fprintf(&sb, `<p class=muted>%s</p>`, esc(n))
	}
	sb.WriteString(`<footer>Generated by Gosper — Hashlife with a hash-consed quadtree.</footer></main></body></html>`)
	return sb.String(), nil
}

const reportHead = `<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{--bg:#fafaf7;--fg:#1c2420;--muted:#5d6b63;--card:#ffffff;--line:#dcdcd2;--accent:#105e36;--accent2:#b4541a}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0d1117;--fg:#e6edf3;--muted:#8b98a5;--card:#161b22;--line:#2a313a;--accent:#7ee787;--accent2:#ffa657}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 48px}
.eyebrow{letter-spacing:.14em;text-transform:uppercase;font-size:12px;color:var(--accent);margin:0 0 4px;font-weight:600}
h1{font-size:2rem;margin:.1em 0 .2em;letter-spacing:-.02em}
h2{font-size:1.15rem;margin:2em 0 .4em}
code{background:var(--card);border:1px solid var(--line);padding:1px 6px;border-radius:5px;font-size:.9em}
.muted{color:var(--muted);margin:.3em 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card .k{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.card .v{font-size:1.25rem;font-weight:650;margin:2px 0;color:var(--accent)}
.card .sub{font-size:.88rem;color:var(--muted)}
.snaps{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px}
figure img{width:100%;height:auto;border-radius:8px;display:block;image-rendering:pixelated}
figcaption{font-size:.85rem;color:var(--muted);margin-top:6px}
.missing{padding:40px 8px;color:var(--accent2);font-size:.9rem}
img.light{display:block}img.dark{display:none}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) img.light{display:none}:root:not([data-theme=light]) img.dark{display:block}}
.chart{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px}
svg{width:100%;height:auto;display:block}
svg .grid{stroke:var(--line);stroke-width:1}
svg .tick{fill:var(--muted);font-size:10.5px}
svg .axis{fill:var(--muted);font-size:11.5px}
svg .line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round}
svg .dot{fill:var(--accent2)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:.9rem}
th,td{text-align:right;padding:4px 10px;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}
details{margin-top:10px}summary{cursor:pointer;color:var(--accent)}
footer{margin-top:40px;color:var(--muted);font-size:.85rem;border-top:1px solid var(--line);padding-top:12px}
</style>`
