// Package report renders self-contained HTML reports (inline SVG, no JS deps).
package report

import (
	"fmt"
	"html"
	"math"
	"os"
	"sort"
	"strings"

	"kepler/data"
	"kepler/gp"
)

// BenchRow is one benchmark outcome for the bench report.
type BenchRow struct {
	Name, Desc, Truth, Found string
	Err                      float64
	OK                       bool
	Result                   *gp.Result
	Data                     *data.Dataset
}

const css = `:root{--bg:#0f1420;--card:#171e2e;--ink:#e8ecf4;--mute:#8d99b3;--line:#2a3550;--acc:#6ee7b7;--acc2:#f6c177;--bad:#f28b82}
@media (prefers-color-scheme:light){:root{--bg:#f4f6fb;--card:#fff;--ink:#16203a;--mute:#5b6784;--line:#d8deec;--acc:#0b8f6a;--acc2:#b36b00;--bad:#c0392b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 60px}h1{font-size:28px;margin:0 0 4px;letter-spacing:-.5px}
h2{font-size:18px;margin:0 0 10px}.sub{color:var(--mute);margin:0 0 24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin:0 0 18px}
.eq{font:600 20px ui-monospace,Menlo,Consolas,monospace;color:var(--acc);word-break:break-word}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--mute);font-weight:600}td.f{font-family:ui-monospace,Menlo,Consolas,monospace}tr.sel td{background:rgba(110,231,183,.12)}
.ok,.tag.ok{color:var(--acc);border-color:var(--acc)}.bad,.tag.bad{color:var(--bad);border-color:var(--bad)}svg{width:100%;height:auto;display:block}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--mute);font-size:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}@media(max-width:760px){.grid{grid-template-columns:1fr}}`

func page(title, body string) string {
	return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>` +
		html.EscapeString(title) + `</title><style>` + css + `</style></head><body><main>` + body + `</main></body></html>`
}

// Write renders a fit report for one dataset.
func Write(path, target string, d *data.Dataset, res *gp.Result, _ []BenchRow) error {
	return os.WriteFile(path, []byte(page("Kepler report", "<h1>Kepler</h1><p class=sub>Symbolic regression report</p>"+fitSection(target, d, res))), 0o644)
}

// WriteBench renders the benchmark summary.
func WriteBench(path string, rows []BenchRow) error {
	var sb strings.Builder
	pass := 0
	for _, r := range rows {
		if r.OK {
			pass++
		}
	}
	fmt.Fprintf(&sb, "<h1>Kepler benchmarks</h1><p class=sub>%d of %d physical laws rediscovered from sampled data</p>", pass, len(rows))
	for _, r := range rows {
		cls, word := "ok", "rediscovered"
		if !r.OK {
			cls, word = "bad", "missed"
		}
		fmt.Fprintf(&sb, `<div class=card><h2>%s <span class="tag %s">%s</span></h2><p class=sub>%s</p><p>truth: <code>%s</code></p>`,
			html.EscapeString(r.Name), cls, word, html.EscapeString(r.Desc), html.EscapeString(r.Truth))
		sb.WriteString(fitSection(r.Data.Target, r.Data, r.Result))
		sb.WriteString("</div>")
	}
	return os.WriteFile(path, []byte(page("Kepler benchmarks", sb.String())), 0o644)
}

func fitSection(target string, d *data.Dataset, res *gp.Result) string {
	var sb strings.Builder
	if res.Selected < 0 {
		return "<p>No valid model found.</p>"
	}
	sel := res.Front[res.Selected]
	fmt.Fprintf(&sb, `<div class=card><h2>Selected model</h2><div class=eq>%s = %s</div><p class=sub>complexity %d · train NMSE %.2e`,
		html.EscapeString(target), html.EscapeString(sel.Tree.Format(res.Names)), sel.Complexity, sel.TrainNMSE)
	if !math.IsNaN(sel.HoldoutNMSE) {
		fmt.Fprintf(&sb, " · holdout NMSE %.2e", sel.HoldoutNMSE)
	}
	sb.WriteString("</p></div><div class=grid><div class=card><h2>Pareto front</h2>")
	sb.WriteString(paretoSVG(res))
	sb.WriteString("</div><div class=card><h2>Fit</h2>")
	sb.WriteString(fitSVG(d, res))
	sb.WriteString("</div></div><div class=card><h2>All Pareto models</h2><table><tr><th>cplx<th>train NMSE<th>holdout<th>formula</tr>")
	for i, m := range res.Front {
		cls := ""
		if i == res.Selected {
			cls = ` class=sel`
		}
		h := "–"
		if !math.IsNaN(m.HoldoutNMSE) {
			h = fmt.Sprintf("%.2e", m.HoldoutNMSE)
		}
		fmt.Fprintf(&sb, "<tr%s><td>%d<td>%.2e<td>%s<td class=f>%s</tr>", cls, m.Complexity, m.TrainNMSE, h, html.EscapeString(m.Tree.Format(res.Names)))
	}
	sb.WriteString("</table></div>")
	return sb.String()
}

func logv(e float64) float64 { return math.Log10(math.Max(e, 1e-16)) }

func paretoSVG(res *gp.Result) string {
	const W, H, L, B, T, R = 460, 300, 52, 36, 14, 14
	f := res.Front
	maxC := 1
	worst, best := math.Inf(-1), math.Inf(1)
	for _, m := range f {
		maxC = max(maxC, m.Complexity)
		v := logv(m.TrainNMSE)
		worst, best = math.Max(worst, v), math.Min(best, v)
	}
	lo, hi := math.Ceil(worst), math.Floor(best) // y axis: lo (top) .. hi (bottom)
	if lo-hi < 2 {
		lo = hi + 2
	}
	x := func(c int) float64 { return L + float64(c)/float64(maxC+1)*(W-L-R) }
	yy := func(v float64) float64 { return T + (lo-v)/(lo-hi)*float64(H-T-B) }
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg viewBox="0 0 %d %d" role="img" aria-label="Pareto front: error versus complexity">`, W, H)
	for v := hi; v <= lo; v++ {
		fmt.Fprintf(&sb, `<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="var(--line)"/><text x="%d" y="%.1f" fill="var(--mute)" font-size="10" text-anchor="end">1e%d</text>`, L, W-R, yy(v), yy(v), L-6, yy(v)+3, int(v))
	}
	fmt.Fprintf(&sb, `<text x="%d" y="%d" fill="var(--mute)" font-size="11" text-anchor="middle">complexity →</text>`, (W+L)/2, H-6)
	var pts []string
	for _, m := range f {
		pts = append(pts, fmt.Sprintf("%.1f,%.1f", x(m.Complexity), yy(logv(m.TrainNMSE))))
	}
	fmt.Fprintf(&sb, `<polyline points="%s" fill="none" stroke="var(--acc2)" stroke-width="2"/>`, strings.Join(pts, " "))
	for i, m := range f {
		fill, r := "var(--acc2)", 4
		if i == res.Selected {
			fill, r = "var(--acc)", 7
		}
		fmt.Fprintf(&sb, `<circle cx="%.1f" cy="%.1f" r="%d" fill="%s"><title>complexity %d, NMSE %.2e</title></circle>`, x(m.Complexity), yy(logv(m.TrainNMSE)), r, fill, m.Complexity, m.TrainNMSE)
	}
	sb.WriteString(`</svg>`)
	return sb.String()
}

// fitSVG plots prediction vs. truth: against the first variable when there is
// one input, otherwise predicted-vs-actual.
func fitSVG(d *data.Dataset, res *gp.Result) string {
	const W, H, L, B, T, R = 460, 300, 46, 34, 14, 14
	sel := res.Front[res.Selected].Tree
	oneD := len(d.Names) == 1
	type pt struct{ x, y, p float64 }
	var ps []pt
	for i, row := range d.X {
		p := sel.Eval(row)
		if math.IsNaN(p) || math.IsInf(p, 0) {
			continue
		}
		xv := row[0]
		if !oneD {
			xv = d.Y[i]
		}
		ps = append(ps, pt{xv, d.Y[i], p})
	}
	if len(ps) == 0 {
		return "<p class=sub>model undefined on the data</p>"
	}
	if oneD {
		sort.Slice(ps, func(i, j int) bool { return ps[i].x < ps[j].x })
	}
	minX, maxX, minY, maxY := math.Inf(1), math.Inf(-1), math.Inf(1), math.Inf(-1)
	for _, q := range ps {
		for _, v := range []float64{q.y, q.p} {
			minY, maxY = math.Min(minY, v), math.Max(maxY, v)
		}
		minX, maxX = math.Min(minX, q.x), math.Max(maxX, q.x)
	}
	if !oneD {
		minX, maxX = minY, maxY
	}
	if maxX == minX {
		maxX = minX + 1
	}
	if maxY == minY {
		maxY = minY + 1
	}
	px := func(v float64) float64 { return L + (v-minX)/(maxX-minX)*float64(W-L-R) }
	py := func(v float64) float64 { return float64(H-B) - (v-minY)/(maxY-minY)*float64(H-T-B) }
	var sb strings.Builder
	fmt.Fprintf(&sb, `<svg viewBox="0 0 %d %d" role="img" aria-label="model fit">`, W, H)
	fmt.Fprintf(&sb, `<rect x="%d" y="%d" width="%d" height="%d" fill="none" stroke="var(--line)"/>`, L, T, W-L-R, H-T-B)
	fmt.Fprintf(&sb, `<text x="%d" y="%d" fill="var(--mute)" font-size="10">%.3g</text><text x="%d" y="%d" fill="var(--mute)" font-size="10">%.3g</text>`, 4, T+10, maxY, 4, H-B, minY)
	xl := html.EscapeString(d.Names[0])
	if !oneD {
		xl = "actual " + html.EscapeString(d.Target)
		fmt.Fprintf(&sb, `<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="var(--acc)" stroke-width="1.5" stroke-dasharray="4 3"/>`, px(minX), py(minY), px(maxX), py(maxY))
	}
	fmt.Fprintf(&sb, `<text x="%d" y="%d" fill="var(--mute)" font-size="11" text-anchor="middle">%s →</text>`, (W+L)/2, H-6, xl)
	for _, q := range ps {
		vy := q.y
		if !oneD {
			vy = q.p
		}
		fmt.Fprintf(&sb, `<circle cx="%.1f" cy="%.1f" r="2.6" fill="var(--acc2)" opacity=".75"/>`, px(q.x), py(vy))
	}
	if oneD {
		var line []string
		for _, q := range ps {
			line = append(line, fmt.Sprintf("%.1f,%.1f", px(q.x), py(q.p)))
		}
		fmt.Fprintf(&sb, `<polyline points="%s" fill="none" stroke="var(--acc)" stroke-width="2"/>`, strings.Join(line, " "))
	}
	sb.WriteString(`</svg>`)
	return sb.String()
}
